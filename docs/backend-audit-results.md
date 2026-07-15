# Backend audit results

Recorded on 2026-07-15 after implementing the phases in `trading_engine_implementation_plan(1).md`. The requested `trading_engine_implementation_plan.md` filename was absent; the `(1)` file was read completely and used as the authoritative plan. The untouched baseline is in [audit-baseline.md](audit-baseline.md).

## Outcome

All final acceptance conditions in the implementation plan are satisfied. The backend, Gateway, streaming, frontend, migration, Compose, smoke, and PostgreSQL concurrency checks pass. There are no known test failures or unresolved implementation blockers.

The deployment remains a single backend application deployment with its existing worker processes and a single Gateway deployment. No authentication, user-specific behavior, tenant behavior, live trading, or additional application service was added. Backend and Gateway startup now reject live configuration; all execution is `SHADOW` or `PAPER`.

## Baseline

The untouched repository passed its existing checks: backend 95 tests, Gateway 18 tests, streaming 3 tests, frontend 21 tests, frontend build, Compose smoke, and streaming recovery smoke. Passing tests did not cover several unsafe behaviors:

- a position snapshot could zero unrelated portfolios;
- reconciliation combined accounts and held external I/O inside a transaction;
- fills did not maintain weighted average cost or realized P&L;
- idempotency keys had no canonical request identity or safe failed-operation retry contract;
- Gateway commands had no ownership lease or crash recovery state;
- terminal rejected/cancelled sells could unlock rebalance buys;
- concurrent orders did not reserve shared account capital;
- the legacy and current strategy implementations both remained active;
- startup used runtime schema adoption and fake-initial migrations;
- strategy readiness, Kafka publishing, market-history writes, and API serialization performed avoidable repeated work;
- optimization and other expensive workflows ran in HTTP workers.

The first baseline Compose inspection encountered an unavailable Docker Desktop Linux-engine pipe. Starting Docker and rerunning succeeded without a code change; this was an environment startup condition, not an application defect.

## Correctness and reliability changes

### Broker state and accounting

- Broker position snapshots now persist account, snapshot identity, completeness, processing status, attempts, and diagnostic payloads. Only complete snapshots are applied, and only to portfolios belonging to the snapshot account. Empty complete snapshots zero only that account; partial snapshots do not mutate positions; duplicate snapshots apply once.
- Reconciliation runs and breaks are broker-account scoped. Gateway I/O occurs before the atomic comparison/write phase, and old breaks are resolved only within the same account/run scope.
- Fill accounting is transactionally idempotent by broker execution ID. Portfolio quantity, weighted average cost, gross realized P&L, cash ledger, position ledger, strategy attribution, and order fill state roll back together on failure.
- Weighted-average behavior, position reversal, realized P&L, and commission treatment are documented in [POSITION_ACCOUNTING.md](POSITION_ACCOUNTING.md).

### Idempotency and crash recovery

- Canonical request hashes now protect Gateway commands, manual orders, strategy-generated intents/actions, portfolio flows, rebalances, and optimizations. Reusing a key with a different request returns a conflict.
- Persisted failures expose error and retryability state. Retrying requires the original key plus `Idempotency-Retry: true`; non-retryable failures remain rejected.
- Concurrent `get_or_create` paths prevent duplicate records at unique idempotency boundaries. A PostgreSQL integration test verifies that two simultaneous manual-order requests produce one intent, one order, and one Gateway placement.
- Gateway commands now have claim owner, claim time, lease expiry, attempt history, broker-submission state, completion state, and retryability. Expired pre-submission commands can be safely reclaimed. Submitted order commands recover through broker references/reconciliation and are not blindly resubmitted when the outcome is uncertain.
- Gateway event acknowledgement requires an idempotency key and a positive sequence. Command endpoints no longer invent idempotency keys.

### Risk, sequencing, and concurrency

- Pre-trade limits are persisted per portfolio instead of accepted from request payloads. Kill switches honor global, account, portfolio, strategy-instance, instrument, and model scopes.
- Capital reservations lock the broker account and include estimated fees. Competing requests cannot reserve the same cash. Reservations are consumed or released with terminal order/flow outcomes.
- Sell-before-buy rebalances gate buys on the configured filled-quantity threshold. Cancelled, rejected, or underfilled sells leave buys blocked; recalculation and restarts remain idempotent.
- PostgreSQL testing found that `FOR UPDATE` across a nullable `strategy_instance` join was rejected by PostgreSQL even though SQLite tests passed. Locking now explicitly targets the base intent row, with the account locked separately. The same base-row targeting was applied to nullable attribution and optimization-application joins.

### Strategy consolidation and failure visibility

- `StrategyInstance` is the only strategy identity used by runtime evaluation, allocation, rebalancing, risk, charts, timelines, deletion, and order attribution.
- Historical financial facts retain immutable strategy identity/version snapshots when a strategy instance is deleted. Active records require an unambiguous migrated instance.
- Exact evaluation readiness is persisted by strategy instance/version and finalized bar/version. A strategy evaluates once only after every required input is present. Warm-up progress is incremental, capped, and correction safe.
- Evaluation work runs inside a rollback savepoint. Plugin failures leave an error run and strategy state without partial signals, targets, or outbox events. Explicit retries restore the retained pre-evaluation state and reuse the same run identity.
- Kafka consumer failures persist a retryable failed-consumption record and a full dead-letter envelope before committing the offset. The health metric is `DEGRADED`, not healthy. Replay can retry the failed event, and replay status is pollable.

### Validation and paper-only enforcement

- Read endpoints reject unsupported methods with structured `405` responses. Mutations validate JSON-object shape, allowed/required fields, supported enum values, exact booleans, relationships, positive finite decimals, field precision, order-type price requirements, and state transitions.
- Manual and Gateway order modification rejects placement-only fields, prices incompatible with the existing order type, and quantity below an already-filled amount.
- Portfolio/universe/policy/optimization, flow, sizing, rebalance, kill-switch, replay, instrument, and Gateway relationships/payloads are validated before work is queued.
- Invalid OMS transitions are explicit and leave no status-history side effect.
- Backend and Gateway fail startup when live mode is requested. Compose fixes the Gateway to paper mode; strategy, rebalance, and optimization APIs accept only observe/shadow/paper behavior.

## Asynchronous and performance changes

- Optimization preview and application, optimization-backed flows, and rebalance planning create durable queued records, dispatch existing Celery workers, and return `202`. The frontend polls run resources through terminal state. History refresh, reconciliation, and Kafka replay also use existing background workers. See [ASYNC_OPERATIONS.md](ASYNC_OPERATIONS.md).
- Kafka outbox publication produces a batch, flushes once, and persists each event's confirmed delivery or retry state. It never marks an event published before acknowledgement.
- Finnhub history ingestion uses bulk conflict-aware writes while preserving corrections and uniqueness.
- API list serialization uses joined/prefetched/subquery data instead of per-row queries. Fixed query budgets with five result rows are:

  | API | Queries |
  | --- | ---: |
  | Strategy instance list | 1 |
  | Strategy instance detail | 3 |
  | Order list, including count | 2 |
  | Positions list | 1 |
  | Allocation policy list | 1 |
  | Rebalance list | 1 |

- Indexes now cover order/intent queues and broker identifiers, Gateway claims/events/health, market bars/indicators/readiness, strategy activity/runs/targets/allocations, rebalance recovery, reconciliation breaks, outbox publication, broker snapshots, portfolio positions, capital reservations, audit aggregates, and dead-letter replay.
- Safe bounded compaction covers acknowledged Gateway events, Gateway health snapshots, published outbox events, completed broker snapshots, terminal readiness rows, and abandoned stream-health metrics. Immutable order, execution, fill, ledger, reconciliation, allocation, identity-snapshot, and audit facts are retained. See [RETENTION_POLICY.md](RETENTION_POLICY.md).

The final suite has substantially more behavioral coverage than the baseline, so total suite time is not a like-for-like performance benchmark. Query-count tests are the repeatable evidence for API scaling; no production-sized load benchmark was performed.

## Deleted legacy code and compatibility changes

Deleted runtime code and documentation:

- `Backend/apps/strategies/engine.py`
- `Backend/apps/strategies/services.py`
- `Backend/apps/core/management/commands/adopt_legacy_schema.py`
- `docs/PAPER_TO_LIVE_CHECKLIST.md`

The `TradingStrategy` and `HistoricalBar` models/tables are removed by staged migrations. The old `/api/v1/strategies/` and `/api/v1/strategy-runs/` routes are removed rather than retained behind compatibility adapters. Clients must use `/api/v1/strategy-instances/` and its action/run resources. This intentional compatibility change is documented in `Backend/README.md`; migration preflight and rollback are documented in [DATABASE_UPGRADES.md](DATABASE_UPGRADES.md).

Runtime schema adoption, `--fake-initial`, and `--run-syncdb` were removed from both entrypoints. Startup runs only `migrate --noinput`.

## Database migrations added

Backend:

- `broker_gateway.0002_brokerpositionsnapshot`
- `portfolios.0002_position_realized_pnl`
- `portfolios.0003_portfolioposition_portfolio_position_time_idx`
- `reconciliation.0002_account_scope`
- `oms.0006_orderintent_idempotency_state`
- `oms.0007_instance_only`
- `oms.0008_order_order_status_updated_idx_and_more`
- `risk.0002_policy_and_capital_reservations`
- `audit.0004_operationattempt`
- `audit.0005_auditevent_audit_aggregate_time_idx_and_more`
- `allocation.0007_operation_idempotency_state`
- `allocation.0008_instance_only`
- `allocation.0009_rebalancerun_rebalance_port_status_idx_and_more`
- `strategies.0004_strategyaction`
- `strategies.0005_prepare_instance_only`
- `strategies.0006_remove_legacy_strategy`
- `strategies.0007_strategyallocation_strategy_alloc_priority_idx_and_more`
- `market_streams.0004_strategyevaluationreadiness_and_more`
- `event_bus.0002_deadletterevent_dead_letter_replay_idx`
- `portfolio_optimization.0003_operation_idempotency_state`
- `portfolio_optimization.0004_alter_portfoliooptimizationrun_application_status`

Gateway:

- `gateway_service.0002_command_leases`
- `gateway_service.0003_gatewayevent_gateway_event_ack_idx_and_more`

The strategy conversion uses prepare, data-migration, reference-removal, and model-deletion stages. It fails instead of guessing when an active legacy reference lacks an unambiguous instance mapping. `tests/test_migration_paths.py` migrates representative old data through the current graph and verifies preserved identity and facts. A fresh Gateway database also applied `0001` through `0003` normally.

## Final verification

| Command | Exact result |
| --- | --- |
| `cd Backend; ../.venv/Scripts/python.exe manage.py check` | Passed: no issues (0 silenced) |
| `cd Backend; ../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| `cd Backend; ../.venv/Scripts/python.exe manage.py migrate --noinput` | Passed; latest `portfolio_optimization.0004` applied normally |
| `cd Backend; ../.venv/Scripts/python.exe -m pytest -q` | **168 passed, 2 skipped in 18.68s** |
| PostgreSQL container concurrency tests | **2 passed in 6.12s**; both local skips executed and passed against PostgreSQL |
| `cd IB_gateway; ../.venv/Scripts/python.exe manage.py check` | Passed: no issues (0 silenced) |
| `cd IB_gateway; ../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | Passed: no changes detected |
| `cd IB_gateway; ../.venv/Scripts/python.exe manage.py migrate --noinput` | Passed on a fresh SQLite database; `0001` through `0003` applied normally |
| `cd IB_gateway; ../.venv/Scripts/python.exe -m pytest -q` | **41 passed in 0.32s** |
| `.venv/Scripts/python.exe -m pytest -q streaming` | **3 passed in 0.03s** |
| `cd Frontend; npm test -- --run` | **3 files passed, 21 tests passed in 8.85s** |
| `cd Frontend; npm run build` | Passed: TypeScript and Vite production build; 1,662 modules; built in 290ms |
| `docker compose up -d --build` | Passed; final rebuild/start completed and backend, Gateway, and frontend reported healthy |
| `docs/compose_smoke.ps1` | Passed: `Compose smoke test passed` |
| `docs/streaming_recovery_smoke.ps1` | Passed: `Streaming recovery smoke test passed` |
| Flink JobManager internal overview | Passed: five jobs present and all five `RUNNING` |
| `git diff --check` | Passed: no whitespace errors |

The backend suite covers complete broker-to-order/fill projection, duplicate requests/events/fills, Gateway recovery, complete/partial/account-scoped position snapshots, weighted accounting and rollback, account-scoped reconciliation, strategy evaluation/readiness/retry, flows and allocations, sell-before-buy sequencing, optimization and application retries, Kafka outbox delivery, dead-letter replay, transaction rollback, capital reservation, and concurrent PostgreSQL requests.

## Remaining limitations and deferred items

- Real IBKR paper-session certification still requires operator credentials, an available paper account, market-data permissions, and qualified contracts. Compose verifies process/HTTP health without claiming a connected broker session.
- Real Finnhub download behavior requires a valid credential. Client retry, secret handling, bulk upsert, correction, failure metadata, and async orchestration are tested with controlled responses.
- Query budgets and targeted PostgreSQL concurrency are verified, but no production-sized latency, throughput, or database load benchmark was run.
- SQLite does not implement PostgreSQL row locks, so the two concurrency tests skip in the fast local suite and are run explicitly against Compose PostgreSQL. Both pass.
- Authentication, user-specific flows, tenant isolation, live trading, additional deployment services, research/backtesting expansion, and HA broker-worker election are intentionally outside scope and were not implemented.

No acceptance item is deferred and no blocker remains.
