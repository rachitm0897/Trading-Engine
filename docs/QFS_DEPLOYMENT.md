# QFS / QCH production deployment

Connect the same repository to QFS three times. Each application uses its component directory as both the QFS root directory and Docker build context. Production does not use a repository-root Dockerfile, Docker Compose, or a `deploy` directory.

Repository for all three applications: `https://github.com/rachitm0897/trading-engine`

| QFS application | Root directory | Dockerfile | Public path | Health URL |
| --- | --- | --- | --- | --- |
| Backend | `Backend` | `Dockerfile` | `/trading_eng_backend` | `https://qfsplatform.com/trading_eng_backend/healthz` |
| Frontend | `Frontend` | `Dockerfile` | `/trading_eng_frontend` | `https://qfsplatform.com/trading_eng_frontend/healthz` |
| Standalone Gateway | `IB_gateway` | `Dockerfile` | `/trading_eng_gateway` | `https://qfsplatform.com/trading_eng_gateway/healthz` |

These three public applications do not provide PostgreSQL, Redis, Kafka, or Flink. Provision those as external services and give their connection URLs only to the Backend application.

## Architecture boundaries

There are six distinct deployment roles:

1. The public Backend QFS app runs Django ASGI, Celery workers, Celery Beat, and the private managed-session noVNC proxy.
2. The public Frontend QFS app serves the React build through Nginx.
3. The public standalone Gateway QFS app is for manual or diagnostic use.
4. Private per-session Gateway children are created by the Backend through QCH. Every `BrokerGatewaySession` has a unique child name, service token, noVNC password, account set, and event cursor.
5. A Docker Hub repository stores the manually published `IB_gateway` image that QCH pulls for private children. It may be private during testing or public for server deployment.
6. External PostgreSQL, Redis, Kafka, and Flink services support the Backend.

The standalone public Gateway never replaces `IBKR_GATEWAY_IMAGE` and is never used as the shared route for managed trading sessions. Managed child URLs always have the form `http://<container-name>:8080/api/v1`. Do not publish child TWS ports 4001/4002, VNC 5900, websockify 6080, internal Gunicorn 8001, or child HTTP 8080. The Backend requires no Docker socket, SSH, or direct Docker daemon access.

## Backend QFS application

Set:

```text
PORT=8000
APP_BASE_PATH=/trading_eng_backend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
ALLOWED_HOSTS=qfsplatform.com
CORS_ALLOWED_ORIGINS=https://qfsplatform.com
CSRF_TRUSTED_ORIGINS=https://qfsplatform.com
DJANGO_SECRET_KEY=<long random secret>
BROKER_SESSION_ENCRYPTION_KEY=<independently managed encryption key>
BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED=false
IBKR_GATEWAY_IMAGE=docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway@sha256:<digest>
BROKER_CREDENTIAL_TTL_SECONDS=900
BROKER_SESSION_CREATING_STALE_SECONDS=60
BROKER_SESSION_START_TIMEOUT_SECONDS=45
BROKER_SESSION_HEALTH_TIMEOUT_SECONDS=5
NOVNC_ACCESS_TOKEN_TTL_SECONDS=300
NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS=10
NOVNC_PROXY_IDLE_TIMEOUT_SECONDS=300
NOVNC_PROXY_MAX_BODY_BYTES=10485760
QCH_REQUEST_TIMEOUT_SECONDS=10
QCH_SUBCONTAINER_NETWORK=traefik
```

Enable QFS **Sub-container management / QCH broker access** for this Backend application. QFS/QCH must inject `QCH_APP_ID`, `QCH_API_HOST`, and the rotated `QCH_SERVICE_TOKEN` into the Backend process environment. Do not set these variables on the Frontend or standalone Gateway. The token is read from the process environment when a QCH client is created and is never stored in the database.

Configure external dependencies:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/trading_engine
REDIS_URL=redis://HOST:6379/0
CELERY_BROKER_URL=redis://HOST:6379/1
CELERY_RESULT_BACKEND=redis://HOST:6379/2
KAFKA_BOOTSTRAP_SERVERS=HOST:9092
KAFKA_ENABLED=true
FLINK_REST_URL=https://FLINK_HOST
```

Also configure `FINNHUB_API_KEY` and the Finnhub timeout/fallback variables when those providers are enabled. Research controls include `RESEARCH_ENABLED`, `RECOMMENDATION_SYSTEM_ENABLED`, bundle/artifact paths, provider, lookback, concurrency, score-age, and cache-age variables listed in [`Backend/.env.example`](../Backend/.env.example). The production image contains its own research bundle and Kafka schemas; it does not read repository-parent files.

`GET /healthz` is process liveness and does not wait for database or recommendation caches. `GET /readyz` checks required database and recommendation-cache readiness and reports only missing or invalid broker/QCH variable names, never the Docker Hub username, repository, tag, digest, visibility, or credentials. Missing managed Gateway configuration does not by itself return HTTP 503. The System API returns the same non-secret broker deployment status, and managed-session actions return `BROKER_GATEWAY_NOT_CONFIGURED` until it is available.

Required public routes include:

```text
/trading_eng_backend/healthz
/trading_eng_backend/readyz
/trading_eng_backend/api/v1/system/
/trading_eng_backend/api/v1/dashboard/summary/
/trading_eng_backend/api/v1/broker-sessions/
/trading_eng_backend/api/v1/broker-sessions/<uuid>/
/trading_eng_backend/api/v1/broker-sessions/<uuid>/novnc/...
```

`/trading_eng_backend/dashboard` redirects to `/trading_eng_backend/api/v1/dashboard/summary/`. The Backend does not contain or serve the React application.

## Frontend QFS application

The Dockerfile builds with `/trading_eng_frontend/` as the deterministic Vite base. It does not require QFS build arguments. At container start, `BACKEND_API_URL` generates a small uncached `runtime-config.js`; the QFS default is already built in.

```text
PORT=5173
APP_BASE_PATH=/trading_eng_frontend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_frontend
BACKEND_API_URL=https://qfsplatform.com/trading_eng_backend/api/v1
```

`VITE_APP_BASE_PATH` remains available as a build-time override for non-QFS builds, and `VITE_API_BASE_URL` remains available for local Vite. The production image does not call `http://backend:8000` or any other Docker DNS name. Nginx serves the SPA shell for direct refreshes including `/dashboard`, `/ibkr-sessions`, and every current React route, with all assets and lazy chunks below `/trading_eng_frontend/`.

## Standalone Gateway QFS application

Set:

```text
PORT=8080
APP_BASE_PATH=/trading_eng_gateway
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_gateway
DJANGO_SECRET_KEY=<long random secret>
GATEWAY_SERVICE_TOKEN=<long random service token>
NOVNC_PASSWORD=<long random noVNC password>
IB_USERNAME=<standalone diagnostic account username>
IB_PASSWORD=<standalone diagnostic account password>
IBC_TRADING_MODE=paper
BROKER_ADAPTER=ib_async
GATEWAY_DB_PATH=/data/gateway.sqlite3
```

`IBC_TRADING_MODE` accepts exactly `paper` or `live`; paper uses TWS/API 4002 and live uses 4001. Configure persistent QFS storage for both `/data` and `/home/ibgateway/Jts`. Only `${PORT}` is public. The useful root response, public health, authenticated API, noVNC asset, and WebSocket paths are:

```text
/trading_eng_gateway/
/trading_eng_gateway/healthz
/trading_eng_gateway/api/v1/health/
/trading_eng_gateway/api/v1/session/
/trading_eng_gateway/novnc/vnc.html
/trading_eng_gateway/novnc/websockify
```

The standalone service is operationally separate from all managed QCH children.

## QCH contract and lifecycle

The Backend uses exactly:

```text
GET    {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers
POST   {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers
DELETE {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers/{url-encoded-container-name}
Authorization: Bearer <QCH_SERVICE_TOKEN>
```

Create sends required `image` and `name`, optional `env` and `network`, and normally omits `command` so the image `ENTRYPOINT` runs. The session environment contains `DJANGO_SECRET_KEY`, `GATEWAY_SERVICE_TOKEN`, `NOVNC_PASSWORD`, `IB_USERNAME`, `IB_PASSWORD`, `IBC_TRADING_MODE`, `BROKER_ADAPTER=ib_async`, `PORT=8080`, and `APP_BASE_PATH=`. The Backend generates the Django secret only for this create request and does not persist it. HTTP 409 and ambiguous retryable creates are resolved by listing and adopting only the expected name. A delete 404 is successful idempotent deletion.

The create API has no registry-authentication fields. The Backend does not run Docker, pull the image itself, accept registry credentials from the browser, store them on sessions, or send them in the QCH request or child environment. QCH receives only the validated configured Docker Hub image reference. An image-pull failure is reported as a generic QCH provisioning failure because it can mean a missing image, a wrong tag or digest, network failure, missing host authentication, rate limiting, or an unsupported architecture; it does not prove the repository is private.

Temporary IBKR credentials are encrypted at rest. They survive retryable QCH/network failures and Celery retries, then are deleted after confirmed creation/adoption, final non-retryable failure, final retry exhaustion, or TTL expiry. The periodic monitor requeues stale `CREATING` sessions so a lost task cannot leave one permanently stuck. When managed QCH deployment is not configured, monitoring exits with a disabled result without changing existing sessions; unrelated Celery work continues. If a private child exits or disappears while QCH is available, the Backend records a visible error, disables trading commands, and waits for explicit credential-based recreation; it does not silently replace the failure.

QCH's child API does **not** expose volume mounting, automatic restart policies, or public Traefik routes. Do not document or depend on those capabilities.

## Managed noVNC and proxy requirements

Managed-session noVNC stays behind the Backend ASGI proxy and never uses `https://qfsplatform.com/trading_eng_gateway`. Authorization, `vnc.html`, and `websockify` paths are generated with exactly one Backend prefix. Both platform behaviors are supported: the prefix may remain in the upstream path, or QFS may strip it and send `X-Forwarded-Prefix`.

The QFS outer proxy must forward `Upgrade` and `Connection` for Backend managed-session WebSockets and standalone Gateway websockify. It must also forward `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Prefix`. Repository code cannot recover a WebSocket upgrade discarded by the outer platform proxy.

Browser input never selects an upstream host, URL, scheme, or port. The proxy preserves binary WebSocket frames and close/disconnect events, validates expiring session-specific access tokens, and completes VNC authentication without returning the child noVNC password to the browser.

## Publish the child image

Publication is currently a manual Docker Hub operation. Build the x86-64 image from the `IB_gateway` context, then log in and push a fixed version:

```bash
cd IB_gateway
docker buildx build --platform linux/amd64 --load -t DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0 .
docker login
docker push DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
docker pull docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
docker image inspect --format='{{index .RepoDigests 0}}' docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
```

The Backend requires the explicit `docker.io/` prefix. Set `IBKR_GATEWAY_IMAGE` to `docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway@sha256:<64-hex-digest>` for production. A fixed tag such as `docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0` is accepted for testing; `latest`, bare repositories, URL-style values, other registries, placeholders, and malformed tags or digests are rejected.

### Private-image testing

```text
Docker Hub repository: private
IBKR_GATEWAY_IMAGE: docker.io/<username>/<repository>:<fixed-version>
QCH host: authenticated with read permission
Backend: no Docker Hub credentials
```

Provision Docker Hub read authentication directly on the QCH/Docker host, outside this repository and outside Backend configuration. The host must be able to perform the equivalent of an authenticated Docker pull. Do not place the token in QFS Backend variables, browser requests, broker-session records, QCH request fields, or child environments.

### Public-image server deployment

```text
Docker Hub repository: public
IBKR_GATEWAY_IMAGE: docker.io/<username>/<repository>@sha256:<digest>
QCH host: no registry authentication required
Backend: unchanged
```

The Backend cannot detect or control image visibility. Changing the same Docker Hub repository from private to public requires no Backend code change, and the same configured image reference may continue to be used. Only the QCH host's need for registry authentication changes.

## Build and post-deployment checks

From the repository root, the production contexts are exactly:

```bash
docker build -t trading-engine-backend ./Backend
docker build -t trading-engine-frontend ./Frontend
docker buildx build --platform linux/amd64 --load -t trading-engine-gateway ./IB_gateway
```

Run containers independently with explicit environment variables; production smoke testing does not connect them with Compose. Local Docker Compose remains a separate development option.

Public checks that require no secret:

```bash
python scripts/qfs_smoke.py
curl -fsS https://qfsplatform.com/trading_eng_backend/healthz
curl -fsS https://qfsplatform.com/trading_eng_frontend/healthz
curl -fsS https://qfsplatform.com/trading_eng_gateway/healthz
```

Set `QFS_GATEWAY_SERVICE_TOKEN` only when also checking the standalone authenticated health/session endpoints. Do not print or persist that token. Deleting a managed Gateway container pauses its bound strategies and monitoring, but does not cancel orders already resting at IBKR.
