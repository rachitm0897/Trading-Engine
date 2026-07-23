# Finflock IBKR Trading Execution Engine

A paper-first execution platform that converts deterministic portfolio targets into risk-checked orders, broker executions, append-only ledgers, and reconciliation records.

## Repository components

- `Backend/` contains Django ASGI, Celery workers, research, allocation, risk, OMS, execution, and reconciliation.
- `Frontend/` contains the React/TypeScript operator application served by Nginx.
- `IB_gateway/` builds the reusable `linux/amd64` Docker Hub image used for one private IBKR session child.
- `streaming/` contains Kafka contracts and PyFlink jobs. PostgreSQL remains the financial source of truth.

Only the private Gateway child owns an `ib_async`/TWS connection. The browser, Frontend, Backend, Kafka, and Flink never connect to a TWS socket directly.

## Production architecture

QFS contains exactly two public applications:

| QFS application | Root/build context | Dockerfile | Public URL |
| --- | --- | --- | --- |
| Frontend | `Frontend` | `Frontend/Dockerfile` | `https://qfsplatform.com/trading_eng_frontend` |
| Backend | `Backend` | `Backend/Dockerfile` | `https://qfsplatform.com/trading_eng_backend` |

PostgreSQL, Redis, Celery storage, Kafka, and Flink are external and are configured only on the Backend. Broker sessions use this path:

```text
Frontend session form
  -> Backend broker-session API
  -> QCH Sub-container Broker API
  -> QCH pulls IBKR_GATEWAY_IMAGE from Docker Hub
  -> one private Gateway child per session
  -> Backend uses http://<child-name>:8080/api/v1
```

The Backend validates and forwards only the configured image reference and child configuration. It does not run Docker, pull images, mount a Docker socket, or accept/store/forward registry credentials. Gateway children publish no host ports; managed noVNC is available only through the Backend broker-session path.

Build and publish the child image separately:

```bash
cd IB_gateway
docker buildx build --platform linux/amd64 --load -t DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0 .
docker push DOCKERHUB_USERNAME/trading-engine-ib-gateway:v1.0.0
```

Production should configure `IBKR_GATEWAY_IMAGE=docker.io/<username>/<repository>@sha256:<64-hex-digest>`. A fixed non-`latest` Docker Hub tag is accepted for controlled testing. See [QFS deployment](docs/QFS_DEPLOYMENT.md) for the complete variable matrix, routes, networking, WebSocket, publication, and access-control requirements.

## Local development

Compose starts PostgreSQL, Redis, Kafka, topic initialization, Flink, Backend, and Frontend. It does not start an IBKR Gateway. Without QCH and `IBKR_GATEWAY_IMAGE`, managed broker-session creation returns a configuration error while the rest of the platform remains available.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
powershell -NoProfile -File docs/compose_smoke.ps1
powershell -NoProfile -File docs/automatic_execution_smoke.ps1
```

- Frontend: <http://localhost:5173>
- Backend system API: <http://localhost:8000/api/v1/system/>
- Backend liveness: <http://localhost:8000/healthz>
- Automatic execution readiness: <http://localhost:8000/api/v1/execution/readiness/>

See [local development](docs/LOCAL_DEVELOPMENT.md), [Portfolio Builder](docs/PORTFOLIO_BUILDER.md), [research universe](docs/RESEARCH_UNIVERSE.md), and [recommendation engine](docs/RECOMMENDATION_ENGINE.md).

## Tests and independent builds

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm ci && npm test && npm run test:production-build
cd .. && python -m pytest streaming/flink/tests
docker compose config --quiet
docker build -t trading-engine-backend ./Backend
docker build -t trading-engine-frontend ./Frontend
docker buildx build --platform linux/amd64 --load -t trading-engine-gateway ./IB_gateway
```

`GET /healthz` is process liveness. Backend `GET /readyz` checks database and
recommendation readiness. `GET /api/v1/execution/readiness/` is the stricter,
fail-closed automatic PAPER readiness report for Flink checkpoints, Kafka and
worker heartbeats, workflow backlogs, market freshness, Gateway connectivity,
broker reconciliation, and uncertain orders. Missing managed-session
configuration does not make process health fail. Live broker sessions remain
subject to `ALLOW_LIVE_TRADING`, kill switches, reconciliation, confirmation,
validation, and pre-trade risk controls.
