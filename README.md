# Finflock IBKR Trading Execution Engine

A paper-first execution platform that converts deterministic portfolio targets into risk-checked orders, broker executions, append-only ledgers, and reconciliation records.

## Applications

- `Backend/` — Django, PostgreSQL, Redis, Celery, research, construction, allocation, risk, OMS, execution, and reconciliation.
- `Frontend/` — React/TypeScript operator application served by Nginx.
- `IB_gateway/` — the per-session `ib_async` connection owner and publishable child-container image, with IB Gateway/IBC and noVNC behind one private Nginx port.
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

`GET /healthz` is process liveness. `GET /readyz` checks required database and recommendation readiness and also reports non-secret managed QCH/broker-session deployment status. Missing or invalid managed Gateway configuration disables only managed sessions and does not by itself make the Backend unready; when recommendations are enabled, readiness still requires the active 500-member universe, 97-entry registry, and all 20 valid timeframe/risk cache profiles to be current.

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
- Local/static gateway health: <http://localhost:8080/healthz>
- Managed sessions and protected noVNC links: <http://localhost:5173/ibkr-sessions>

Compose retains one explicitly local/static real-adapter gateway for legacy development flows. Production execution never uses it: the Backend provisions one QCH child container per IBKR session and resolves every broker call through the portfolio's stored session. The Sessions page requires QCH variables and a published `IBKR_GATEWAY_IMAGE`. No demo account, portfolio, instrument, or order data is created.

## Tests

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
cd .. && ./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

See [local development](docs/LOCAL_DEVELOPMENT.md), [Portfolio Builder](docs/PORTFOLIO_BUILDER.md), [research universe](docs/RESEARCH_UNIVERSE.md), [backtesting](docs/BACKTESTING_PROTOCOL.md), [promotion](docs/STRATEGY_PROMOTION.md), and the [recommendation engine](docs/RECOMMENDATION_ENGINE.md).

## QFS / QCH production

Enter `https://github.com/rachitm0897/trading-engine` into QFS three times:

| Application | QFS root / Docker context | Dockerfile | Public path |
| --- | --- | --- | --- |
| Backend | `Backend` | `Dockerfile` | `/trading_eng_backend` |
| Frontend | `Frontend` | `Dockerfile` | `/trading_eng_frontend` |
| Standalone Gateway | `IB_gateway` | `Dockerfile` | `/trading_eng_gateway` |

No repository-root build, `deploy` directory, Compose stack, or hidden frontend build argument is required. PostgreSQL, Redis, Kafka, and Flink remain external. Only the Backend receives `QCH_APP_ID`, `QCH_API_HOST`, and `QCH_SERVICE_TOKEN` and provisions one private child Gateway per managed session. The public standalone Gateway is manual/diagnostic and is never a shared managed-session route.

Build and publish the child image before enabling managed sessions:

```bash
docker build -t ghcr.io/OWNER/trading-engine-ib-gateway:GIT_COMMIT_SHA ./IB_gateway
docker push ghcr.io/OWNER/trading-engine-ib-gateway:GIT_COMMIT_SHA
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/OWNER/trading-engine-ib-gateway:GIT_COMMIT_SHA
```

Set `IBKR_GATEWAY_IMAGE` to `ghcr.io/OWNER/trading-engine-ib-gateway@sha256:<digest>`. The GHCR package must be public or the QCH host must have registry authentication. See the exact app settings, routes, storage, WebSocket requirements, smoke commands, and QCH limitations in [QFS deployment](docs/QFS_DEPLOYMENT.md).

> Live gateway sessions are supported, but live orders still require the independent `ALLOW_LIVE_TRADING=true` deployment gate and all existing kill switches, reconciliation, confirmation, validation, and pre-trade risk controls. Actionable recommendations remain long-only; short and pair/basket execution remain disabled.
