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

`POST /api/v1/market-data/history/` is an authenticated, durable, read-only broker command. It requires an exact positive conId and supports `1 min`, `5 mins`, `15 mins`, `1 hour`, and `1 day` bars with `TRADES` or `ADJUSTED_LAST`. Intraday duration is bounded to 90 days and daily duration to ten years.

`POST /api/v1/market-data/schedule/` returns up to 365 days of exact-contract historical trading sessions. Backend uses it to validate intraday research windows. Both routes are idempotent durable commands; neither opens an order path nor a live subscription.
