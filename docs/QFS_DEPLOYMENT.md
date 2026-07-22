# QFS / QCH production deployment

Connect `https://github.com/rachitm0897/trading-engine` to QFS exactly twice. Each application uses its component directory as both the QFS root and Docker build context.

| QFS application | Root/build context | Dockerfile | Public URL | Health check |
| --- | --- | --- | --- | --- |
| Frontend | `Frontend` | `Frontend/Dockerfile` | `https://qfsplatform.com/trading_eng_frontend` | `/healthz` |
| Backend | `Backend` | `Backend/Dockerfile` | `https://qfsplatform.com/trading_eng_backend` | `/healthz` |

There is no third public application. `IB_gateway/` is only the source for a reusable private child image published to Docker Hub. PostgreSQL, Redis, Celery broker/result storage, Kafka, and Flink are external services configured only on the Backend.

## Architecture

```text
Browser
  -> Frontend QFS app
  -> Backend QFS app
       -> external PostgreSQL / Redis / Kafka / Flink
       -> QCH Sub-container Broker API
            -> pulls configured Docker Hub image
            -> starts one private Gateway child per BrokerGatewaySession
       -> http://<full-session-uuid-child-name>:8080/api/v1
```

The Backend never pulls an image. It has no Docker SDK, Docker CLI, Docker socket, SSH deployment, or Compose execution path. The browser cannot supply an image reference or any registry authentication. The database and child environment contain no Docker Hub credentials. QCH receives only the validated configured image reference and permitted child configuration.

## Environment matrix

| Owner | Variables |
| --- | --- |
| Frontend QFS app | `PORT`, `BACKEND_API_URL` |
| Backend QFS app | `PORT`, `APP_BASE_PATH`, `PUBLIC_BASE_URL`, `FORWARDED_ALLOW_IPS`, `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, external infrastructure URLs, `IBKR_GATEWAY_IMAGE`, `BROKER_SESSION_ENCRYPTION_KEY`, optional `QCH_SUBCONTAINER_NETWORK`, trading/provider/research policy overrides |
| QCH-injected Backend values | `QCH_APP_ID`, `QCH_API_HOST`, `QCH_SERVICE_TOKEN` |
| Per-session child environment | `DJANGO_SECRET_KEY`, `GATEWAY_SERVICE_TOKEN`, `NOVNC_PASSWORD`, `IB_USERNAME`, `IB_PASSWORD`, `IBC_TRADING_MODE`, `BROKER_ADAPTER`, `PORT` |
| Optional local development | PostgreSQL credentials, host ports, local Django/encryption secrets, CORS/CSRF origins, SHADOW execution mode, optional Finnhub key |

Do not configure IBKR usernames/passwords on either QFS application. They are submitted per session, encrypted temporarily by the Backend, sent once to QCH, and deleted after confirmed creation/adoption or final expiry/failure.

## Frontend QFS application

Set:

```text
PORT=5173
BACKEND_API_URL=https://qfsplatform.com/trading_eng_backend/api/v1
```

The production Vite base is deterministically `/trading_eng_frontend/`. React Router uses Vite's normalized `BASE_URL`, so routes and built assets share one prefix. Nginx:

- permanently redirects `/trading_eng_frontend` to `/trading_eng_frontend/`;
- serves the SPA shell for `/dashboard`, `/ibkr-sessions`, and all other deep links;
- serves assets and lazy chunks below `/trading_eng_frontend/`;
- serves both prefixed and application-root upstream paths;
- serves `/runtime-config.js` with `Cache-Control: no-store`;
- serves `/healthz` without depending on the Backend.

Container startup accepts only a single-line HTTP(S) `BACKEND_API_URL` from a restricted URL character set before inserting it into JavaScript. Quotes, whitespace, line breaks, and malformed schemes fail startup. The production browser never uses Docker DNS.

## Backend QFS application

Set the public/runtime fundamentals:

```text
PORT=8000
APP_BASE_PATH=/trading_eng_backend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
FORWARDED_ALLOW_IPS=*
DJANGO_SECRET_KEY=<long random secret>
ALLOWED_HOSTS=qfsplatform.com
CORS_ALLOWED_ORIGINS=https://qfsplatform.com
CSRF_TRUSTED_ORIGINS=https://qfsplatform.com
BROKER_SESSION_ENCRYPTION_KEY=<independent long random key>
IBKR_GATEWAY_IMAGE=docker.io/<dockerhub-user>/<repository>@sha256:<64-hex-digest>
```

Configure external dependencies only here:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/trading_engine
REDIS_URL=redis://HOST:6379/0
CELERY_BROKER_URL=redis://HOST:6379/1
CELERY_RESULT_BACKEND=redis://HOST:6379/2
KAFKA_BOOTSTRAP_SERVERS=HOST:9092
KAFKA_ENABLED=true
FLINK_REST_URL=https://FLINK_HOST
```

Enable QFS Sub-container management for this Backend app. QCH must inject:

```text
QCH_APP_ID
QCH_API_HOST
QCH_SERVICE_TOKEN
```

`QCH_SUBCONTAINER_NETWORK` is optional. Leave it blank to omit `network` from the create payload and use QCH's platform default. Set it only when QFS requires an explicit shared network that resolves child container names from the Backend.

The QFS process health check must use `/healthz`, not `/readyz`. `/healthz` is process liveness. `/readyz` checks the database and recommendation cache; missing managed-session configuration alone does not make either endpoint fail.

Required public routing:

```text
/trading_eng_backend
/trading_eng_backend/healthz
/trading_eng_backend/readyz
/trading_eng_backend/api/v1/system/
/trading_eng_backend/api/v1/broker-sessions/
/trading_eng_backend/api/v1/broker-sessions/<uuid>/novnc/...
```

The exact base returns useful JSON metadata. Django routes work when QFS preserves the prefix and when QFS strips it before forwarding. In stripped mode, QFS must send `X-Forwarded-Prefix: /trading_eng_backend`.

## QCH contract

The Backend uses only:

```text
GET    {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers
POST   {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers
DELETE {QCH_API_HOST}/api/apps/{QCH_APP_ID}/containers/{url-encoded-child-name}
Authorization: Bearer <QCH_SERVICE_TOKEN>
```

New deterministic child names contain the full session UUID. Create sends `name`, `image`, `env`, and optionally `network`; it omits `command` so the image entrypoint runs. The child environment is exactly:

```text
DJANGO_SECRET_KEY=<generated per create request>
GATEWAY_SERVICE_TOKEN=<generated per session>
NOVNC_PASSWORD=<generated per session>
IB_USERNAME=<submitted per session>
IB_PASSWORD=<submitted per session>
IBC_TRADING_MODE=paper|live
BROKER_ADAPTER=ib_async
PORT=8080
```

Managed child URLs are always `http://<child-container-name>:8080/api/v1`. Do not publish child port `8080` or private TWS, VNC, websockify, and Gunicorn listeners. HTTP 409 and ambiguous retryable creates are resolved by listing and adopting only the expected deterministic name. Delete 404 is successful idempotent deletion.

## Docker Hub image policy

Build and publish from `IB_gateway` only:

```bash
cd IB_gateway
docker buildx build --platform linux/amd64 --load -t DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0 .
docker push DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
docker pull docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
docker image inspect --format='{{index .RepoDigests 0}}' docker.io/DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
```

Production uses the returned `docker.io/<username>/<repository>@sha256:<digest>` reference. Fixed non-`latest` Docker Hub tags remain available for controlled testing. `latest`, placeholders, whitespace/line breaks, malformed references, URL-style values, bare repositories, and other registries are rejected.

For a private Docker Hub repository, authenticate the QCH host with read access outside this repository. For a public repository, QCH needs no registry credentials. Backend behavior is identical and never exposes repository visibility or credentials.

## Managed noVNC and outer-proxy requirements

The Backend ASGI proxy handles noVNC HTTP assets and WebSockets at the broker-session path. Generated URLs contain exactly one Backend prefix. The outer QFS proxy must preserve:

- `Upgrade` and `Connection` for WebSockets;
- `X-Forwarded-Proto` and `X-Forwarded-Host`;
- `X-Forwarded-Prefix` when it strips the public path.

Repository code cannot recover an upgrade removed by the outer proxy. Browser input cannot select the child host, scheme, port, or URL. Expiring session tokens authorize noVNC, and the Backend terminates VNC authentication so the child password does not reach the browser.

## Access-control production gate

Health endpoints remain public. Before declaring deployment production-ready, verify that QFS protects both public applications upstream. If it does not, state-changing trading, provider, strategy, and broker-session APIs must not remain anonymously reachable. Use the existing Django staff-session authentication for application-level protection where needed; do not introduce a second authentication system.

## Build and smoke checks

```bash
docker build -t trading-engine-backend ./Backend
docker build -t trading-engine-frontend ./Frontend
docker buildx build --platform linux/amd64 --load -t trading-engine-gateway ./IB_gateway
python scripts/qfs_smoke.py
```

Compose is a local development tool and is not a production deployment path.
