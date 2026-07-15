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

Health: `GET /healthz`. APIs use `/api/v1/` and return the documented `{ok,data,error,meta}` envelope. `APP_BASE_PATH` may be empty or a QFS prefix. The application is paper-only and fails startup if live mode is requested.

Database startup uses normal Django migrations only. See [`docs/DATABASE_UPGRADES.md`](../docs/DATABASE_UPGRADES.md) before upgrading an existing installation.

Optimization previews/applications, optimization-backed portfolio flows, rebalances, history refreshes, reconciliation, and Kafka replay execute as background jobs. Their write endpoints return `202 Accepted` while queued; poll the corresponding run-detail endpoint until a terminal status. See [`docs/ASYNC_OPERATIONS.md`](../docs/ASYNC_OPERATIONS.md).

The legacy `/api/v1/strategies/` and `/api/v1/strategy-runs/` contracts were deleted with the legacy strategy engine. Use `/api/v1/strategy-instances/` and its action/run resources. This is an intentional compatibility break: financial history is retained through immutable strategy snapshots, while no runtime compatibility layer remains.
