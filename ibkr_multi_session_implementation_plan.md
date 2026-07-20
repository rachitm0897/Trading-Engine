# IBKR Multi-Session Gateway Implementation Plan

## 1. Target behaviour

Build one IBKR Sessions screen with no application login or logout flow.

From this screen, the operator can:

1. Enter an IBKR username and password.
2. Select exactly one mode: `paper` or `live`.
3. Start a new isolated IB Gateway Docker container through the existing QCH Sub-container Broker API.
4. Run two or more gateway sessions at the same time.
5. See each session's provisioning, login, connection and error state.
6. For a live session, open a proxied noVNC window and complete IBKR 2FA.
7. See all IBKR accounts exposed by each connected session.
8. switch the selected session and account without restarting another session.
9. Delete a gateway container from the frontend.
10. Continue using the existing trading engine with every broker request routed through the correct session.

Do not add user authentication. This is therefore a private, single-operator deployment until authentication is added later.

---

## 2. Non-negotiable architecture decisions

### Use the QCH broker API only

The backend must use:

- `QCH_APP_ID`
- `QCH_API_HOST`
- `QCH_SERVICE_TOKEN`

It must not mount `/var/run/docker.sock`, call the Docker daemon directly, use SSH, or require server credentials.

### One backend session record per child gateway

The backend owns a persistent record for every requested gateway container. It must never infer the active gateway from one global environment variable.

### Strict mode validation

Only these normalized values are valid:

- `paper`
- `live`

Reject `shadow`, `test`, `demo`, empty strings and unknown values. Remove only the code that blocks live IBKR sessions and assumes one paper gateway. Preserve risk checks, kill switches, order validation, audit records and reconciliation.

### Dynamic internal routing

Each child gateway receives a unique Docker name and is reached through the shared Docker network:

`http://<container-name>:8080/api/v1`

The browser must never receive this hostname.

### Backend-proxied noVNC

QCH child containers have no public Traefik route. The backend must proxy both noVNC HTTP assets and its WebSocket connection.

Run the backend as ASGI and implement a session-ID-based proxy. Never accept an arbitrary upstream hostname or URL from the browser.

---

## 3. Data model

Create a backend model such as `BrokerGatewaySession`.

Recommended fields:

- UUID primary/public identifier
- operator-provided display name
- masked username hint, never the password
- mode with database choices `paper` and `live`
- status
- container name
- container ID
- internal base URL
- encrypted gateway service token
- encrypted noVNC password
- last gateway state
- last error
- created, provisioned, connected, last checked and deleted timestamps
- version field or row locking support for concurrent lifecycle operations

Recommended status values:

- `CREATING`
- `STARTING`
- `WAITING_FOR_LOGIN`
- `WAITING_FOR_2FA`
- `CONNECTED`
- `DISCONNECTED`
- `LOGIN_FAILED`
- `ERROR`
- `STOPPING`
- `DELETED`

Create a short-lived `BrokerGatewaySessionSecret` model:

- one-to-one relation to the session
- encrypted IBKR username
- encrypted IBKR password
- creation and expiry timestamps

The provisioning task consumes and deletes this row in a `finally` block. A failed retry must require the operator to enter credentials again.

Create `BrokerSessionAccount`:

- session FK
- existing `BrokerAccount` FK
- first seen and last seen timestamps
- availability flag
- optional alias returned by IBKR
- unique constraint on `(session, broker_account)`

Bind execution deterministically:

- add a gateway-session relation to `TradingPortfolio`, or add an equivalent explicit broker-route model used by every order
- validate that the portfolio's account is exposed by that session
- never route an order using a global “currently selected session”

Change `BrokerSyncCursor` from one global cursor to a cursor scoped by gateway session.

Include the session ID in broker snapshot keys, event identities, command idempotency keys and imported-order identities to prevent collisions between child gateways.

---

## 4. QCH container broker client

Add a dedicated backend client, separate from `GatewayClient`.

Responsibilities:

- read QCH environment variables at request/task execution time
- list child containers
- create a child container
- delete a child container
- translate QCH HTTP errors into typed application errors
- apply timeouts and bounded retries only to safe operations
- never log request environment values or authorization headers

Container creation must use:

- image from `IBKR_GATEWAY_IMAGE`
- unique name such as `trading-engine-ibkr-<short-uuid>`
- network from `QCH_SUBCONTAINER_NETWORK`, default `traefik`
- generated gateway service token
- generated noVNC password
- runtime environment:
  - `IB_USERNAME`
  - `IB_PASSWORD`
  - `IBC_TRADING_MODE`
  - `GATEWAY_SERVICE_TOKEN`
  - `NOVNC_PASSWORD`
  - `BROKER_ADAPTER=ib_async`
  - `PORT=8080`
  - `APP_BASE_PATH=`
  - any existing required gateway settings

A repeated provisioning task must be idempotent:

- lock the session row
- if the recorded container name already exists in the app-scoped QCH list, adopt it and continue health checks
- never create a second container for the same session record
- handle a 409 name collision explicitly

The QCH API cannot build the repository Dockerfile. The IB Gateway image must be published to a registry or already be pullable by the host. Pin production to an immutable image digest where possible.

---

## 5. Backend lifecycle API

Add endpoints under `/api/v1/broker-sessions/`.

### `POST /broker-sessions/`

Payload:

```json
{
  "display_name": "Primary live",
  "username": "...",
  "password": "...",
  "mode": "live"
}
```

Behaviour:

- validate exact allowed modes
- validate non-empty credentials and bounded lengths
- create the session and encrypted temporary secret
- enqueue provisioning with Celery
- return `202` with the session object
- never return or log credentials

### `GET /broker-sessions/`

Return all non-purged sessions, including:

- ID
- display name
- masked username
- mode
- lifecycle status
- connected state
- account count
- last error
- timestamps
- whether noVNC should be opened

### `GET /broker-sessions/<uuid>/`

Return detailed status and discovered accounts.

### `POST /broker-sessions/<uuid>/reconnect/`

Call the correct gateway using its per-session URL and token.

### `POST /broker-sessions/<uuid>/credentials/`

Allow credentials to be resubmitted after `LOGIN_FAILED` or `ERROR`. Recreate the container only through the lifecycle service.

### `DELETE /broker-sessions/<uuid>/`

Make deletion idempotent:

1. mark the session `STOPPING`
2. reject new commands for that session
3. pause strategy instances and market subscriptions bound to it
4. mark in-flight broker state as requiring reconciliation
5. call QCH delete
6. mark the session `DELETED`
7. preserve audit/history records

Deletion does not cancel open orders already resting at IBKR. Show this clearly in the API response and frontend confirmation.

### Accounts

Add:

- `GET /broker-sessions/<uuid>/accounts/`
- account and session filters to relevant portfolio/account APIs

Return a default portfolio ID for each discovered session-account pair, so the frontend can switch the rest of the engine to the correct portfolio context.

---

## 6. Provisioning and monitoring tasks

Add Celery tasks:

### Provision session

1. lock session
2. decrypt temporary credentials
3. call QCH create
4. save container ID/name and internal URL
5. poll child `/healthz`
6. poll authenticated gateway `/api/v1/health/`
7. update state
8. delete temporary credentials in `finally`

Status rules:

- child HTTP service unavailable: `STARTING`
- child service healthy but IBKR disconnected:
  - live: `WAITING_FOR_2FA`
  - paper: `WAITING_FOR_LOGIN`
- broker connected: `CONNECTED`
- explicit gateway error or expired login window: `LOGIN_FAILED`
- infrastructure/QCH failure: `ERROR`

For live mode, set `WAITING_FOR_2FA` as soon as the gateway web service is ready. The frontend should immediately offer noVNC. Do not claim that 2FA is complete until the gateway reports `CONNECTED`.

### Monitor sessions

Run periodically:

- list active sessions
- call each child health endpoint
- update status and timestamps
- synchronize accounts/events with an independent cursor per session
- detect containers missing from QCH
- mark them `DISCONNECTED` or `ERROR`
- do not silently create replacement live sessions using stored credentials, because credentials are intentionally removed

QCH does not auto-restart child containers. Recovery must be explicit and visible.

---

## 7. Make the gateway image support both modes

Update `IB_gateway`:

- remove the startup exception that rejects live mode
- normalize `IBC_TRADING_MODE`
- reject every value except `paper` and `live`
- set TWS/API port dynamically:
  - paper: `4002`
  - live: `4001`
- write the normalized mode to IBC configuration
- expose the normalized mode in health/session responses
- preserve the current gateway service-token protection
- preserve order validation and command idempotency
- add useful session state fields such as last connection error and connection time
- ensure credentials are not printed by management commands, shell tracing, Supervisor or logs

Keep noVNC and the gateway REST API on the existing internal port `8080`.

---

## 8. Convert all backend gateway use to session-aware routing

Refactor `GatewayClient` so construction requires a `BrokerGatewaySession` or an explicit resolved route object.

Remove production use of:

- global `IB_GATEWAY_SERVICE_URL`
- global `GATEWAY_SERVICE_TOKEN`
- parameterless `GatewayClient()`

Audit every call site, including:

- gateway health/reconnect
- accounts and account summary
- positions
- executions
- open/completed orders
- contract search and qualification
- historical data
- market-data subscriptions
- order placement, modification and cancellation
- event synchronization
- reconciliation
- streaming/fallback logic
- readiness and system-health reporting

For order operations, derive the session from the order's portfolio route. Reject an order with a clear error when its bound session is unavailable.

For background synchronization:

- iterate active sessions
- use a cursor per session
- pass session context through every event-processing function
- include session identity in all generated idempotency keys

Do not introduce a hidden global active session.

---

## 9. noVNC HTTP and WebSocket proxy

The existing backend runs WSGI Gunicorn, which cannot proxy noVNC WebSockets correctly.

Change the backend to ASGI using a maintained stack such as:

- Django ASGI
- Channels or a small explicit ASGI router
- Uvicorn worker under Gunicorn
- `httpx` for streamed HTTP proxying
- a maintained WebSocket client for bidirectional forwarding

Proxy routes should resemble:

- HTTP: `/api/v1/broker-sessions/<uuid>/novnc/<path>`
- WebSocket: `/api/v1/broker-sessions/<uuid>/novnc/websockify`

Rules:

- resolve container hostname only from the database session record
- reject deleted or unavailable sessions
- enforce a generated session-specific noVNC access token
- store only its hash where possible
- never allow client-supplied host, port or scheme
- limit headers, body size, idle time and connection duration
- support WebSocket close and cancellation correctly
- preserve binary frames
- rewrite the noVNC connection path so assets and WebSockets remain under the backend public URL

Return the prepared noVNC URL from the session API. The frontend should not construct an internal gateway URL.

Because there is no application login, document that the deployment must remain private or be protected at the platform/reverse-proxy level.

---

## 10. Single-screen frontend

Create one `IBKR Sessions` page. Do not add login, logout, registration or a wizard.

### Start-session panel

Fields:

- optional display name
- IBKR username
- IBKR password
- segmented/radio mode control with only `Paper` and `Live`
- Start session button

Behaviour:

- password is never saved to local storage
- clear username/password after a successful request
- disable duplicate submission while pending
- show backend validation errors without echoing secrets

### Session list/cards

For every session show:

- display name
- masked username
- paper/live badge
- lifecycle/connection badge
- container status
- discovered account count
- last checked time
- last error
- buttons for:
  - select
  - open noVNC
  - reconnect
  - re-enter credentials
  - delete

For live sessions that are not connected, show:

`Open noVNC and complete IBKR 2FA.`

The noVNC action should be available for both modes, but highlighted for live.

### Account switching

When a session is selected:

- load its accounts
- show an account dropdown
- show account summary
- store only selected session ID and account/portfolio ID in frontend state or local storage
- pass explicit IDs to API queries
- never mutate a backend-wide global active account

If no account has been discovered, show the gateway login status instead of an empty table.

### Delete confirmation

Explain:

- the Docker container will be removed
- monitoring will stop
- existing IBKR orders are not automatically cancelled
- bound strategies will be paused

After deletion, remove it from active lists but allow the audit/history record to remain visible.

Do not redesign unrelated trading-engine pages.

---

## 11. Configuration and deployment documentation

Add/update `.env.example` and deployment documentation for:

- `IBKR_GATEWAY_IMAGE`
- `QCH_SUBCONTAINER_NETWORK=traefik`
- `BROKER_SESSION_ENCRYPTION_KEY`
- session start and health timeout settings
- noVNC token TTL
- public backend base URL
- QCH-injected variables

Remove the backend's production dependency on a statically deployed `IB_gateway` application.

Keep an explicitly named local/static development profile only if existing local development would otherwise become unusable. It must not be the production path and must not reintroduce global routing into application code.

Document how to build and publish `IB_gateway` as a registry image.

---

## 12. Tests

### Backend unit tests

Cover:

- strict `paper`/`live` validation
- encryption/decryption and secret deletion
- QCH request construction
- authorization headers never appearing in logs
- idempotent provisioning
- QCH 409 handling
- per-session `GatewayClient`
- per-session event cursors
- account discovery and session-account mapping
- order routing by portfolio session
- deletion lifecycle
- live status transition to `WAITING_FOR_2FA`

### Gateway tests

Cover:

- paper selects port `4002`
- live selects port `4001`
- invalid mode fails startup/configuration
- health responses expose normalized mode
- no credential leakage

### noVNC proxy tests

Cover:

- HTTP asset forwarding
- binary WebSocket forwarding
- invalid session
- deleted session
- invalid/expired access token
- arbitrary-host injection attempts
- upstream disconnect and timeout

### Frontend tests

Cover:

- exactly two mode choices
- request payload
- password clearing
- multiple simultaneous session cards
- live 2FA notice
- account switching
- noVNC link from API
- reconnect
- deletion confirmation and refresh
- backend error states

### Integration/smoke tests

Use a mocked QCH broker plus two fake gateway services to prove:

1. paper and live sessions can be created concurrently
2. each session uses different URL/token/cursor
3. accounts remain isolated
4. selecting one account does not change another session
5. deleting one session leaves the other working
6. live session exposes noVNC and becomes connected after simulated 2FA
7. no credentials appear in responses, database rows after provisioning or logs

Run all existing backend, gateway and frontend tests as regression coverage.

---

## 13. Implementation order

1. Add models, encryption utility and migrations.
2. Add QCH client and lifecycle service.
3. Make the gateway image accept paper/live.
4. Refactor `GatewayClient` to require session context.
5. Migrate broker sync and execution call sites.
6. Add session APIs and Celery tasks.
7. Move backend to ASGI and implement noVNC proxy.
8. Build the single sessions screen.
9. Add lifecycle monitoring, account binding and deletion handling.
10. Add tests and deployment documentation.
11. Run full regression and remove dead static-gateway code.

Do not leave both global and session-aware production paths active. That creates ambiguous routing and will eventually send an order through the wrong gateway, which is an unusually expensive way to discover a leftover default argument.

---

## 14. Acceptance criteria

The implementation is complete only when:

- two or more sessions can run concurrently
- every session has its own credentials, token, container and event cursor
- paper and live are the only accepted modes
- live mode is no longer rejected at backend or gateway startup
- live sessions provide a working proxied noVNC WebSocket
- accounts are listed per session
- the operator can switch session/account context
- orders and market-data calls route through the intended session
- a container can be deleted from the frontend
- deletion of one session does not affect another
- credentials are not returned, logged or retained after provisioning
- all new tests and existing regression tests pass
- production no longer relies on one static gateway URL
