# Implementation status

Updated 2026-07-13.

| Area | Status | Notes |
|---|---|---|
| Three-application/Compose bootstrap | Implemented | One exposed port per application; PostgreSQL and Redis private. |
| Gateway one-port runtime | Implemented | Nginx, noVNC, Supervisor, IBC, Gateway, Django, and broker worker included. |
| Gateway command/event durability | Implemented | SQLite WAL, idempotent commands, ordered events, acknowledgement, mock/ib_async adapters. |
| Backend financial domain | Implemented | Core models, ledgers, audit/outbox, OMS, fills, risk, reconciliation records. |
| Strategies and allocation | Implemented | Exactly five engines, reproducible run hash, aggregation, lot rounding, notional suppression. |
| Configurable streaming strategies | Implemented | Definition/instance/version domain, five plugins, schema validation, canonical contract resolution, shared input registry, dynamic bars/indicators, isolated state, common targets, netting/version attribution, management APIs, terminal builder and monitor. |
| Frontend | Implemented | Five bookmarkable operator sections, typed route queries, schema-driven strategy creation, real persisted charts, responsive layouts, QFS base path, controls and status. |
| Automated unit tests | Implemented | Backend, Gateway, and Frontend suites use mocks and no real IBKR account. |
| Kafka event foundation | Implemented | 21 private topics, including the active strategy-input registry; versioned envelopes, acknowledged transactional outbox publishing, retry, idempotent consumption, DLQ, replay and Prometheus metrics. |
| PyFlink market processing | Implemented | Stable UIDs; normalization/dedup/DLQ; event-time 1m/5m/1d versioned OHLCV; indicators; stale timers; checkpoints/savepoints and checkpoint restore. |
| Market persistence | Implemented | Dedicated Backend consumer persists versioned bars, parameter-versioned indicators and auditable price quality with replay-safe uniqueness. |
| Flow allocation | Implemented | Deficit deposits, reserves/capacity/min/max/priority/rounding, staged withdrawals, five liquidation policies, capital snapshots and idempotent runs. |
| Rebalancing | Implemented | Target netting, weights/drift, lot/economic/turnover/cash/fee controls, sell-before-buy, partial-fill recalculation, attribution and restart deduplication. |
| Position sizing | Implemented | Target/risk/concentration/liquidity/cash/broker limits, binding constraints, invalid-stop/short rejection and volatility cap/renormalization. |
| Streaming/allocation UI and APIs | Implemented | Three terminal pages plus sizing detail, requested v1 APIs, idempotency keys and order-free previews. |
| Real IBKR validation | Operator required | Requires paper credentials, 2FA, subscriptions, and contract universe. |
| Production hardening | Partially implemented | See limitations/open questions for calendars, HA, alerting, and policy values. |

Final verification on 2026-07-11:

- Backend: 16 tests passed.
- Gateway: 9 tests passed.
- Frontend: 4 tests passed; TypeScript and Vite production build passed; production dependency audit reported zero vulnerabilities.
- `docker compose up --build -d`: passed from clean volumes; all five services healthy.
- Live mock contract: place, modify, and cancel commands completed and emitted ordered Gateway events.
- Gateway security: unauthenticated API returned 401; only port 8080 was published; no raw TWS/VNC listener was exposed.
- Real paper verification: IB Gateway 1045 ran under IBC, noVNC displayed the connected Gateway window, API client 17 connected, and real IBKR account values and positions synchronized into PostgreSQL. Demo/test database and Gateway volumes were removed before verification.

Kafka/Flink/allocation extension verification on 2026-07-11:

- Backend: 39 tests passed, covering outbox retry, schemas, replay/idempotency, allocation, rebalancing recovery, sizing, APIs and the idempotency-header CORS contract.
- PyFlink calculation tests: 3 passed; Frontend: 4 passed and production build passed.
- Backend, Frontend, Flink JobManager and Flink TaskManager images built successfully.
- Kafka was healthy, 20 topics initialized, and all five Flink jobs reached `RUNNING` with no failed tasks.
- TaskManager and JobManager recovery smoke tests passed; available state restored from durable checkpoint metadata.
- An existing pre-migration PostgreSQL volume upgraded without dropping data.
- `docs/compose_smoke.ps1` passed with eight running services and no public Kafka/Flink ports.

New execution defaults to `SHADOW`. `NEW_EXECUTION_MODE=PAPER` permits planners to emit only `OrderIntent`; it never bypasses sizing, risk, OMS, Gateway, ledgers or reconciliation. Live mode is unsupported for the new workflows.

Configurable strategy extension verification on 2026-07-13:

- Backend: 49 tests passed. New coverage includes immutable version creation, default shadow mode, management APIs/live rejection, asynchronous IBKR conId qualification persistence, the TSLA RSI(14)/5-minute/30-to-65/5% paper target-to-intent example, target persistence across `HOLD` runs, RSI ticker portability (TSLA/AAPL), RSI/SMA strategy portability, shared indicators, final-input readiness, corrected-bar/replay idempotency, plugin exception isolation, multi-strategy paper netting, signed version attribution through partial and final fills, and attributed-position recovery. Existing restart/recovery, Kafka replay, risk, OMS, ledger, and reconciliation tests remain green.
- Frontend: 5 tests passed and the TypeScript/Vite production build passed. The strategy builder renders plugin schemas, canonical ticker input, timeframe/target/risk/order controls, shadow/observe/paper modes, warm-up requirements, monitoring filters, and enable/pause/flatten controls. Live is not presented.
- Streaming calculation tests pass with registry-parameterized indicator computation. Flink jobs contain no ticker filter and bar timeframes are parsed from active `strategy.inputs.v1` requirements rather than a fixed TSLA/5-minute branch.
- Five built-in definitions are data-backed: RSI mean reversion, SMA crossover, Donchian breakout, volatility-target momentum, and fixed-weight rebalance. Plugins only return signals/targets and have no broker dependency.

Operator paper certification still requires an authenticated IBKR paper session, qualified contracts, market-data permissions, and sufficient warm-up bars. No migration or API enables live trading.
