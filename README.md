# Finflock IBKR Trading Execution Engine

A paper-first execution platform that turns deterministic strategy targets into aggregated portfolio targets, risk-checked orders, broker executions, append-only ledgers, and reconciliation records. It is a new, self-contained codebase; the referenced `ibkr_gateway_docker_prototype` is not a dependency and was not modified.

## Applications

- `Backend/` — Django/DRF, PostgreSQL, Redis, Celery, strategy/allocation/risk/OMS/execution/reconciliation.
- `Frontend/` — React/TypeScript terminal UI served by Nginx.
- `IB_gateway/` — one-port Django, IBC, IB Gateway, Xvfb/Fluxbox, VNC/noVNC, Nginx, Supervisor, and the sole `ib_async` worker.

`streaming/` contains private Kafka contracts and PyFlink jobs; it is infrastructure, not a fourth public application. PostgreSQL remains the financial source of truth. Strategies, Kafka, Flink and the Frontend cannot access the TWS socket; only the Gateway worker connects to `127.0.0.1:4001/4002`.

Kafka carries versioned immutable events through a transactional PostgreSQL outbox. PyFlink normalizes market data, creates event-time 1m/5m/1d OHLCV bars, computes SMA/RSI/Donchian/momentum/volatility/average-volume indicators and publishes price-quality transitions. Backend consumers persist outputs idempotently. Allocation and rebalancing are shadow-first and can create only `OrderIntent`; sizing, risk, OMS, Gateway, ledgers and reconciliation remain mandatory.

## Local start

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
powershell -NoProfile -File docs/compose_smoke.ps1
```

Local URLs:

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:8000/api/v1/system/>
- Gateway health: <http://localhost:8080/healthz>
- noVNC: <http://localhost:8080/novnc/vnc.html>

Compose defaults to the real `ib_async` broker adapter in paper mode. Supply IBKR and noVNC secrets in the root `.env`, start the stack, and use noVNC for login/2FA when IBKR requires operator action. Accounts, account values, positions, open/completed orders, and executions are synchronized through the Gateway event buffer into Backend PostgreSQL. No demo portfolio, instrument, account, or order data is created.

## Tests

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
cd .. && ./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
docker compose up --build -d
docker compose ps
powershell -NoProfile -File docs/streaming_recovery_smoke.ps1
```

See [local development](docs/LOCAL_DEVELOPMENT.md) and each application README for isolated commands.

## QFS

The supported public URLs are:

- `https://qfsplatform.com/trading_eng_backend`
- `https://qfsplatform.com/trading_eng_frontend`
- `https://qfsplatform.com/trading_eng_gateway`

Each application exposes one configurable `${PORT}`. Base paths, public URLs, and forwarded headers are configurable; see [QFS deployment](docs/QFS_DEPLOYMENT.md).

> Paper trading is the default. Do not enable live trading until every item in the [paper-to-live checklist](docs/PAPER_TO_LIVE_CHECKLIST.md) is verified. This first release does not provide market calendars, tax-lot accounting, HA broker-worker election, or a general research/backtesting system.
