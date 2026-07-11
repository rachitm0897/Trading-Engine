# IB Gateway service

One-port Django service for IB Gateway, IBC, noVNC, Nginx, Supervisor, and the sole `ib_async` connection owner. Nginx is the only public listener. The TWS sockets (`127.0.0.1:4001/4002`), VNC (`127.0.0.1:5900`), websockify (`127.0.0.1:6080`), and Gunicorn (`127.0.0.1:8001`) are never published.

Local Compose uses `BROKER_ADAPTER=mock`, so the full stack and tests need no brokerage credentials. For an IBKR deployment set `BROKER_ADAPTER=ib_async`, inject credentials through secrets/environment, and complete IBKR Mobile 2FA through `/novnc/vnc.html`. The SQLite command/event buffer uses WAL mode and is not the financial source of truth.

```bash
cp .env.example .env
pip install -r requirements.txt
python manage.py migrate --run-syncdb
pytest
```

`GET /healthz` is public for infrastructure probes. Every `/api/v1/*` route requires `Authorization: Bearer <GATEWAY_SERVICE_TOKEN>`. Order-changing requests should also send `Idempotency-Key`.

