# Trading Engine Backend

This branch is the standalone Django/ASGI execution service. The image runs
Gunicorn, Celery Beat, the market-stream and Finnhub consumers, and dedicated
Celery workers for `strategy_evaluation`, `target_coordination`,
`intent_execution`, and `broker_commands` under Supervisor. Intent execution
and broker dispatch use separate processes so readiness can prove each
financial handoff is staffed. Startup applies Django migrations before serving
traffic.

It contains its own application source, migrations, tests, research bundle, and packaged Kafka schemas. A normal clone of this branch is sufficient to build and test the Backend; no Frontend, Gateway-image, streaming-infrastructure, sibling checkout, or repository-parent build context is required.

## Build and run

From the repository root:

```bash
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py runserver 8000
```

Build the production image from the same root:

```bash
docker build -t trading-engine-backend .
```

The image contains no environment file. Copy `.env.example` to an ignored `.env` only for local development.

## QFS deployment

Preserve these QFS application settings:

```text
PORT=8000
APP_BASE_PATH=/trading_eng_backend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
```

Set `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, and `BROKER_SESSION_ENCRYPTION_KEY` with deployment-specific values. PostgreSQL, Redis, Kafka, and Flink are external services configured through `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `KAFKA_BOOTSTRAP_SERVERS`, and `FLINK_REST_URL`. Backend policy, execution-mode, research, and provider variables are documented in `.env.example`.

The QFS proxy may preserve the configured prefix or strip it while supplying `X-Forwarded-Prefix`. Managed noVNC traffic requires WebSocket `Upgrade` and `Connection` headers to be preserved.

## Managed IBKR sessions

The runtime contract is:

```text
browser request
  -> Backend broker-session API
  -> QCH Sub-container Broker API
  -> QCH pulls the configured Gateway image
  -> private Gateway child on port 8080
```

QCH injects `QCH_APP_ID`, `QCH_API_HOST`, and `QCH_SERVICE_TOKEN` into the Backend. `QCH_SUBCONTAINER_NETWORK` is optional. Configure the child image as an immutable Docker Hub reference:

```text
IBKR_GATEWAY_IMAGE=docker.io/<username>/<repository>@sha256:<64-hex-digest>
```

The Backend sends QCH the validated image reference and permitted child configuration. It does not build or pull the image, run Compose, use the Docker CLI or SDK, mount `/var/run/docker.sock`, or handle Docker Hub credentials. It reaches a child only through its authenticated internal HTTP API. Missing QCH or image configuration disables managed-session operations without making Backend liveness fail.

## Public routes

With the production prefix, prepend `/trading_eng_backend` to these routes:

- `GET /` returns service and route metadata.
- `GET /healthz` reports process liveness for the QFS health check.
- `GET /readyz` reports database and recommendation-cache readiness.
- `GET /api/v1/execution/readiness/` reports fail-closed automatic PAPER
  readiness and returns 503 with named blockers when execution must stop.
- `GET /metrics` exposes service metrics.
- `/api/v1/system/`, `/api/v1/accounts/`, `/api/v1/instruments/`, `/api/v1/portfolios/`, `/api/v1/positions/`, `/api/v1/orders/`, `/api/v1/executions/`, `/api/v1/risk/`, `/api/v1/audit/`, and `/api/v1/reconciliation/` expose the core operational API.
- `/api/v1/broker-sessions/` manages private Gateway children and proxies their noVNC sessions.
- `/api/v1/strategy-*`, `/api/v1/allocations/`, `/api/v1/rebalancing/`, `/api/v1/position-sizing/`, `/api/v1/portfolio-optimization/`, and `/api/v1/portfolio-construction/` expose trading workflows.
- `/api/v1/streaming/`, `/api/v1/data-providers/`, and `/api/v1/research/` expose streaming, provider, and research operations.

API responses retain the `{ok,data,error,meta}` envelope. Liveness and
readiness are intentionally distinct: `/healthz` proves the process can serve
requests, `/readyz` checks required application dependencies, and
`/api/v1/execution/readiness/` verifies the stricter Flink, Kafka, worker,
market, Gateway, reconciliation, backlog, and uncertain-order gates for
automatic PAPER execution.

## Tests and checks

```bash
pip install -r requirements.txt
python manage.py check --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.test_settings
pytest -q
docker build -t trading-engine-backend .
```

Tests use SQLite through `config.test_settings` and do not require live brokerage credentials. See `docs/` for database upgrades, asynchronous operations, research, risk, accounting, and strategy-plugin guidance.
