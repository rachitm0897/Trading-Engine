# Backend

Django/DRF execution core backed by PostgreSQL and Redis. Supervisor runs Gunicorn, Celery, and Celery Beat in the single deployable application container. The Backend never opens a TWS socket; all broker operations use the authenticated Gateway REST client.

## Run and test

```bash
cp .env.example .env
pip install -r requirements.txt
python manage.py migrate --run-syncdb
python manage.py runserver 8000
pytest
```

Health: `GET /healthz`. APIs use `/api/v1/` and return the documented `{ok,data,error,meta}` envelope. `APP_BASE_PATH` may be empty or a QFS prefix. Paper mode is the default; live mode still requires Gateway live mode and cleared reconciliation/kill-switch gates.

