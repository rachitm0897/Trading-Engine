# Finflock IBKR Trading Execution Engine

A paper-first execution platform that converts deterministic portfolio targets into risk-checked orders, broker executions, append-only ledgers, and reconciliation records.

## Applications

- `Backend/` — Django, PostgreSQL, Redis, Celery, research, construction, allocation, risk, OMS, execution, and reconciliation.
- `Frontend/` — React/TypeScript operator application served by Nginx.
- `IB_gateway/` — the sole `ib_async` connection owner, plus IB Gateway/IBC and noVNC behind one public Nginx port.
- `streaming/` — private Kafka contracts and PyFlink jobs; PostgreSQL remains the financial source of truth.

Strategies, Kafka, Flink, and the frontend cannot access the TWS socket. Kafka uses a transactional PostgreSQL outbox; sizing, risk, OMS, Gateway, ledgers, kill switch, and reconciliation remain mandatory.

The [Portfolio Builder](docs/PORTFOLIO_BUILDER.md) now uses Goals → Recommendations → Preview & Apply. One plan-level request selects diversified stocks and one primary long-only strategy per stock from cached full-universe research. Duplicate stocks and compatible identities aggregate across goals into one combined target. Generation creates no orders, rebalances, strategy instances, enablement, or LIVE path; apply remains explicit and every created or updated instance remains disabled in SHADOW.

The [Research Universe](docs/RESEARCH_UNIVERSE.md) validates and imports the complete 500-stock/97-strategy bundle. Every catalogue strategy has an explicit audited Python implementation and scope-aware engine; JSON formula text is metadata and is never evaluated. Incremental daily/intraday data, corporate actions, fundamentals, analyst estimates, events, point-in-time features, bounded experiments, role-specific scores, and recommendation caches run outside web requests. Pair/basket models remain research-only until atomic multi-instrument and short execution exist.

After activating the bundle, run:

```powershell
cd Backend
python manage.py bootstrap_recommendation_system
python manage.py warm_recommendation_cache
```

The scheduled data, feature, experiment, and scoring tasks must run before Tier 1 caches are expected. Finalists are exactly IBKR-qualified with deterministic substitutions. Missing optional data moves through explicit stale/full, price-only, baseline, and validated-snapshot fallbacks; the system never invents data, scores, contracts, or SHADOW evidence.

`GET /healthz` is the process/database liveness probe. `GET /readyz` is the recommendation deployment gate and returns ready only after the active 500-member universe, 97-entry registry, and all 20 valid timeframe/risk cache profiles are current. Route recommendation traffic only after `/readyz` returns 200.

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

Compose defaults to the real adapter in IBKR paper mode. Supply credentials in `.env` and use noVNC for login/2FA. No demo account, portfolio, instrument, or order data is created.

## Tests

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
cd .. && ./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

See [local development](docs/LOCAL_DEVELOPMENT.md), [Portfolio Builder](docs/PORTFOLIO_BUILDER.md), [research universe](docs/RESEARCH_UNIVERSE.md), [backtesting](docs/BACKTESTING_PROTOCOL.md), [promotion](docs/STRATEGY_PROMOTION.md), and the [recommendation engine](docs/RECOMMENDATION_ENGINE.md).

## QFS

Supported public URLs are:

- `https://qfsplatform.com/trading_eng_backend`
- `https://qfsplatform.com/trading_eng_frontend`
- `https://qfsplatform.com/trading_eng_gateway`

Each application exposes one configurable `${PORT}`. See [QFS deployment](docs/QFS_DEPLOYMENT.md).

> LIVE configuration is rejected at startup. Actionable recommendations are long-only. Intraday, income, event, selector, allocator, and overlay research contribute when point-in-time data is available; short and pair/basket execution remain disabled.
