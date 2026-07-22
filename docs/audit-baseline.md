# Backend Audit Baseline

Recorded on 2026-07-15 before behavioural implementation changes.

## Scope and repository state

- The requested `./trading_engine_implementation_plan.md` was not present. The complete plan was available as `trading_engine_implementation_plan(1).md` and is treated as the authoritative plan.
- No `AGENTS.md` files were present.
- The pre-existing Git working tree contained only two untracked user files: `prompt.txt` and `trading_engine_implementation_plan(1).md`.
- The deployment topology is one Django backend container, one gateway container, one frontend container, and private PostgreSQL, Redis, Kafka, and Flink infrastructure. No additional application service is required by the plan.
- Local execution defaults to SHADOW. Private child-image validation defaults to paper mode; `ALLOW_LIVE_TRADING` defaults to false.

## Baseline checks and tests

| Command | Untouched result |
| --- | --- |
| `cd Backend; ../.venv/Scripts/python.exe manage.py check` | Passed: no issues (0 silenced) |
| `cd Backend; ../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| `cd Backend; ../.venv/Scripts/python.exe -m pytest -q` | Passed: 95 tests in 9.09s |
| `cd IB_gateway; ../.venv/Scripts/python.exe -m pytest -q` | Passed: 18 tests in 0.23s |
| `.venv/Scripts/python.exe -m pytest -q streaming/flink/tests` | Passed: 3 tests in 0.03s |
| `cd Frontend; npm test` | Passed: 3 files, 21 tests in 9.43s |
| `cd Frontend; npm run build` | Passed: 1,662 modules transformed; production bundle built in 367ms |
| `docker compose config --quiet` | Passed |
| `docker compose up --build -d` | Passed; all application health dependencies completed |
| `powershell -NoProfile -File docs/compose_smoke.ps1` | Passed |
| `powershell -NoProfile -File docs/streaming_recovery_smoke.ps1` | Passed; all five Flink jobs returned to `RUNNING` after the scripted restart |

The first `docker compose ps -a` attempt failed because the Docker Desktop Linux-engine pipe was not available. A subsequent `docker compose up --build -d` started the engine and stack successfully without a repository change. This was an environment startup condition, not a repeatable application failure.

## Migration baseline

`makemigrations --check` found no model drift. The local SQLite development database initially had these committed migrations unapplied:

- `strategies.0003`
- `instruments.0003`
- `portfolio_optimization.0001` and `.0002`
- `allocation.0004` through `.0006`
- `audit.0003`
- `market_data.0001` through `.0003`
- `market_streams.0003`
- `oms.0004` and `.0005`

`python manage.py migrate --noinput` applied all of them successfully. The containerized PostgreSQL database also reached a healthy backend state during Compose startup.

Normal backend startup currently runs `adopt_legacy_schema` and `migrate --fake-initial --noinput`. This violates Phase 6 and must be removed after a normal migration path and upgrade procedure are verified.

## Component verification

- PostgreSQL, Redis, Kafka, gateway, backend, and frontend containers reported healthy.
- Kafka topic initialization exited successfully.
- Flink JobManager and TaskManager were running. The normalization, bar aggregation, indicator, stale-price, and stream-health jobs all reported `RUNNING` after recovery smoke testing.
- Backend HTTP health returned 200 with a connected database.
- Frontend and private child-image health endpoints returned 200 during their respective validation runs.
- Backend process inspection confirmed Gunicorn, a two-process Celery worker, Celery Beat, and `consume_market_streams` were running.
- Gateway process inspection confirmed the paper-mode IB Gateway/IBC process, the sole broker worker, Gunicorn, and Nginx were running.
- The Supervisor configuration does not expose a `supervisorctl` control section, so component verification used `docker compose top` and health endpoints.

## Important execution paths identified

- Broker truth is captured by the gateway worker as snapshots/events, pulled by `apps.broker_gateway.sync.sync_events`, projected into account/order/fill/position models, then acknowledged.
- `sync_positions` currently zeros every portfolio before applying a snapshot, regardless of broker account or snapshot completeness.
- Reconciliation currently aggregates positions and executions across every account, resolves old breaks globally, and updates every account's reconciliation flag together.
- Fill application is transactionally idempotent by `execution_id`, but the portfolio position average cost is not updated and realized P&L is not recorded.
- Gateway commands currently have a unique idempotency key but no request hash, ownership lease, crash recovery metadata, or uncertain-submission recovery.
- Rebalance buys currently become eligible when all sells are merely terminal, so rejected/cancelled sells can incorrectly unlock buys.
- Order risk accepts caller-supplied limits and does not reserve capital across concurrent operations.
- `TradingStrategy` and the newer `StrategyInstance` coexist, with duplicate references and an old engine still active.
- Reconciliation performs external gateway calls inside a database transaction.
- Historical market data uses row-by-row upserts; Kafka publishing flushes once per event; strategy readiness is re-evaluated after both bar and indicator persistence using repeated count queries.
- Portfolio optimization and some external data work still execute directly in HTTP request paths.

These findings define the starting point for the ordered implementation phases. Later results and exact final verification are recorded in `docs/backend-audit-results.md`.
