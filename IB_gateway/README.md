# IB Gateway service

One-port Django service for IB Gateway, IBC, noVNC, Nginx, Supervisor, and the sole `ib_async` connection owner. Nginx is the only public listener. The TWS sockets (`127.0.0.1:4001/4002`), VNC (`127.0.0.1:5900`), websockify (`127.0.0.1:6080`), and Gunicorn (`127.0.0.1:8001`) are never published.

Local Compose uses `BROKER_ADAPTER=ib_async` and paper mode. Inject credentials through secrets/environment and complete IBKR Mobile 2FA through `/novnc/vnc.html` when requested. The worker publishes full broker snapshots every five seconds; the SQLite command/event buffer uses WAL mode and is not the financial source of truth. Automated tests still use the explicit mocked adapter and require no brokerage account.

```bash
cp .env.example .env
pip install -r requirements.txt
python manage.py migrate --noinput
pytest
```

`GET /healthz` is public for infrastructure probes. Every `/api/v1/*` route requires `Authorization: Bearer <GATEWAY_SERVICE_TOKEN>`. Order-changing requests should also send `Idempotency-Key`.
# Bounded research history

`POST /api/v1/market-data/history/` is an authenticated, durable, read-only broker command. It requires an exact positive conId and supports only `1 day` bars, `TRADES` or `ADJUSTED_LAST`, and a duration no longer than five years. It never opens an order path or a live market-data subscription.
