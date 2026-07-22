# Backend

Django/DRF execution core backed by PostgreSQL and Redis. Supervisor runs Gunicorn, Celery, and Celery Beat in the single deployable application container. The Backend never opens a TWS socket; all broker operations use the authenticated Gateway REST client.

## Run and test

```bash
cp .env.example .env
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py runserver 8000
pytest
```

Process liveness is `GET /healthz`; required database/recommendation readiness is `GET /readyz`. The readiness and System responses report non-secret managed Gateway configuration status, but missing QCH or child-image configuration disables only managed sessions and does not by itself return HTTP 503. APIs use `/api/v1/` and return the documented `{ok,data,error,meta}` envelope. `APP_BASE_PATH` may be empty locally or `/trading_eng_backend` on QFS. Managed sessions accept only `paper` and `live`; live order execution still requires the independent `ALLOW_LIVE_TRADING` gate and every existing safety control.

`docker build -t trading-engine-backend .` works from this directory. Runtime Kafka schemas and the canonical research bundle are packaged below `Backend`, so the production image does not depend on its repository parent. The QFS container listens on `${PORT:-8000}` and runs Django ASGI, Celery workers, and Celery Beat under Supervisor. PostgreSQL, Redis, Kafka, and Flink URLs must reference external services in production.

Managed broker sessions use QCH private children at `http://<container-name>:8080/api/v1`; they never use the public standalone Gateway. `IBKR_GATEWAY_IMAGE` accepts only an explicit Docker Hub reference: use `docker.io/<username>/<repository>@sha256:<64-hex-digest>` for production or a fixed non-`latest` tag such as `docker.io/<username>/<repository>:v1.0.0` for testing. The Backend validates and sends that configured reference through the QCH create contract and never accepts or stores Docker Hub credentials.

For private-image testing, authenticate the QCH/Docker host with read permission so it can perform the equivalent of an authenticated pull; keep all registry credentials outside the Backend, frontend, session database, and child environment. For public deployment, no Docker Hub authentication is required. Repository visibility is not detected or controlled by the Backend, so changing the same repository from private to public requires no Backend code change. QCH access variables belong only on the Backend application. See [`docs/QFS_DEPLOYMENT.md`](../docs/QFS_DEPLOYMENT.md).

Database startup uses normal Django migrations only. See [`docs/DATABASE_UPGRADES.md`](../docs/DATABASE_UPGRADES.md) before upgrading an existing installation.

Optimization previews/applications, optimization-backed portfolio flows, rebalances, history refreshes, reconciliation, and Kafka replay execute as background jobs. Their write endpoints return `202 Accepted` while queued; poll the corresponding run-detail endpoint until a terminal status. See [`docs/ASYNC_OPERATIONS.md`](../docs/ASYNC_OPERATIONS.md).

The legacy `/api/v1/strategies/` and `/api/v1/strategy-runs/` contracts were deleted with the legacy strategy engine. Use `/api/v1/strategy-instances/` and its action/run resources. This is an intentional compatibility break: financial history is retained through immutable strategy snapshots, while no runtime compatibility layer remains.
