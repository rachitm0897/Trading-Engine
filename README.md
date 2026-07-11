# Finflock IBKR Trading Execution Engine

A paper-first execution platform that turns deterministic strategy targets into aggregated portfolio targets, risk-checked orders, broker executions, append-only ledgers, and reconciliation records. It is a new, self-contained codebase; the referenced `ibkr_gateway_docker_prototype` is not a dependency and was not modified.

## Applications

- `Backend/` — Django/DRF, PostgreSQL, Redis, Celery, strategy/allocation/risk/OMS/execution/reconciliation.
- `Frontend/` — React/TypeScript terminal UI served by Nginx.
- `IB_gateway/` — one-port Django, IBC, IB Gateway, Xvfb/Fluxbox, VNC/noVNC, Nginx, Supervisor, and the sole `ib_async` worker.

PostgreSQL and Redis are local infrastructure services. Strategies and the Frontend cannot access the TWS socket; only the Gateway worker connects to `127.0.0.1:4001/4002`.

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

Compose defaults to the mock broker and paper mode, so it starts without an IBKR account. To authenticate a real paper account, set `BROKER_ADAPTER=ib_async`, supply secrets outside source control, restart the Gateway, and complete 2FA over noVNC.

## Tests

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

See [local development](docs/LOCAL_DEVELOPMENT.md) and each application README for isolated commands.

## QFS

The supported public URLs are:

- `https://qfsplatform.com/trading_eng_backend`
- `https://qfsplatform.com/trading_eng_frontend`
- `https://qfsplatform.com/trading_eng_gateway`

Each application exposes one configurable `${PORT}`. Base paths, public URLs, and forwarded headers are configurable; see [QFS deployment](docs/QFS_DEPLOYMENT.md).

> Paper trading is the default. Do not enable live trading until every item in the [paper-to-live checklist](docs/PAPER_TO_LIVE_CHECKLIST.md) is verified. This first release does not provide market calendars, tax-lot accounting, HA broker-worker election, or a general research/backtesting system.
