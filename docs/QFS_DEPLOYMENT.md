# QFS / QCH deployment

Deploy `Backend/` and `Frontend/` as the two public applications. Do not deploy one shared public Gateway application. The Backend asks the app-scoped QCH Sub-container Broker to create a private `IB_gateway` child for every session, and exposes protected noVNC HTTP/WebSocket routes through its ASGI endpoint.

Backend essentials:

```text
APP_BASE_PATH=/trading_eng_backend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
CORS_ALLOWED_ORIGINS=https://qfsplatform.com/trading_eng_frontend
CSRF_TRUSTED_ORIGINS=https://qfsplatform.com/trading_eng_frontend
BROKER_SESSION_ENCRYPTION_KEY=<long deployment secret>
IBKR_GATEWAY_IMAGE=ghcr.io/ORG/finflock-ibkr-gateway@sha256:<digest>
QCH_SUBCONTAINER_NETWORK=traefik
BROKER_SESSION_START_TIMEOUT_SECONDS=45
BROKER_SESSION_HEALTH_TIMEOUT_SECONDS=5
QCH_REQUEST_TIMEOUT_SECONDS=10
NOVNC_ACCESS_TOKEN_TTL_SECONDS=300
NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS=10
NOVNC_PROXY_IDLE_TIMEOUT_SECONDS=300
NOVNC_PROXY_MAX_BODY_BYTES=10485760
ALLOW_LIVE_TRADING=false
BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED=false
```

QCH must inject `QCH_APP_ID`, `QCH_API_HOST`, and `QCH_SERVICE_TOKEN` into the Backend application. Never expose the QCH token to the Frontend or a child. The Backend passes a unique generated `GATEWAY_SERVICE_TOKEN` and `NOVNC_PASSWORD`, plus the submitted IBKR credentials, only in the child creation environment. Temporary credentials are encrypted at rest and deleted after every provisioning attempt.

Frontend build variables:

```text
VITE_API_BASE_URL=https://qfsplatform.com/trading_eng_backend/api/v1
VITE_APP_BASE_PATH=/trading_eng_frontend/
APP_BASE_PATH=/trading_eng_frontend
```

The Backend serves WebSockets through Uvicorn workers. Configure the platform proxy to preserve `Upgrade` and `Connection` for `/api/v1/broker-sessions/<uuid>/novnc/websockify`, and pass `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Prefix`. The proxy validates the expiring browser token and terminates the child's VNCAuth handshake with the encrypted per-session noVNC password, so that password is never returned to the browser. Child ports 4001, 4002, 5900, 6080, 8001, and 8080 must remain private.

Build and publish the child image before deployment because QCH pulls images and cannot build `IB_gateway/Dockerfile`:

```bash
docker build -t ghcr.io/ORG/finflock-ibkr-gateway:TAG ./IB_gateway
docker push ghcr.io/ORG/finflock-ibkr-gateway:TAG
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/ORG/finflock-ibkr-gateway:TAG
```

Use the reported immutable digest for `IBKR_GATEWAY_IMAGE`. The registry must be readable by the QCH host.

This application intentionally has no user authentication. Keep it private or put platform-level identity/access control in front of both applications. A noVNC access token prevents guessable proxy URLs but is not a substitute for application authentication.

The repository assumes the documented app-scoped broker contract at `QCH_API_HOST/api/v1/apps/<QCH_APP_ID>/subcontainers` supports list, create, and delete with bearer `QCH_SERVICE_TOKEN`, and that a created child is addressable by its assigned name on `QCH_SUBCONTAINER_NETWORK`. QCH child auto-restart and server changes are outside this repository; the periodic monitor reports missing/exited children instead of masking them.
