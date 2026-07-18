# Recommendation MVP runbook

The only operational recommendation universe is AAPL, JPM, XOM, JNJ, and WMT crossed with `FIXED_WEIGHT_REBALANCE`, `SMA_CROSSOVER`, `RSI_MEAN_REVERSION`, `DONCHIAN_BREAKOUT`, and `VOLATILITY_TARGET_MOMENTUM`. The full imported 500 x 97 catalogue is retained for research and future expansion.

Run from `Backend` after the bundle is active:

```powershell
..\.venv\Scripts\python.exe manage.py bootstrap_recommendation_mvp
```

The idempotent command maps the five members, reports exact-contract gaps, validates the five code adapters, refreshes verified-symbol Finnhub data with corporate actions and IBKR fallback, validates 756+ daily bars, creates exactly 25 deterministic experiment groups, reuses unchanged completed inputs, runs changed trials, calculates complete metrics, scores every compatible resolved timeframe/risk pair, advances lifecycle state, and prints a 5 x 5 matrix.

For a new Compose data volume, validate and activate the bundled catalog before bootstrap:

```powershell
docker compose exec -T backend python manage.py validate_research_bundle /research_bundle
docker compose exec -T backend python manage.py import_research_bundle /research_bundle --activate
docker compose exec -T backend python manage.py bootstrap_recommendation_mvp
```

Compose reads `.env` when a container is created. After adding or changing `FINNHUB_API_KEY`, recreate the backend and wait for it to become healthy before testing the provider:

```powershell
docker compose up -d --force-recreate backend
```

Bootstrap deliberately reports, but never guesses, missing IBKR contracts. Each pilot member must be assigned the single exact SMART/USD stock `conId` selected from authenticated Gateway search results before Finnhub mapping can be verified.

Readiness endpoints are read-only. Administrative mutation remains command-line only:

```text
GET /api/v1/research/mvp/status/
GET /api/v1/research/mvp/matrix/
GET /api/v1/research/mvp/stocks/
GET /api/v1/research/mvp/strategies/
```

The after-close Celery task uses a Redis lock and executes the same idempotent pipeline with bounded sequential work. A failed prerequisite remains `BLOCKED` or `SUSPECT`; the pipeline never guesses a contract, replaces a stock, invents a score, creates an order, enables a strategy, or changes `NEW_EXECUTION_MODE`. SHADOW/PAPER are the only accepted execution modes and `ALLOW_LIVE_TRADING=true` still fails startup.
