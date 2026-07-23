# Automatic strategy execution architecture

## Status and scope

This document is the ownership contract for automatic strategy execution.
Durable strategy evaluation, portfolio target coordination, intent execution,
broker-command dispatch, fill accounting, and execution readiness are
implemented and covered by the automatic PAPER integration test.

The only supported automatic order path is:

<!-- automatic-pipeline:start -->
```text
Market provider
-> market.raw.v1
-> Flink normalization
-> Flink bars and indicators
-> Kafka derived-market topics
-> Backend market persistence
-> StrategyEvaluationJob
-> Strategy evaluation worker
-> StrategyTarget
-> PortfolioTargetSnapshot
-> RebalanceRun
-> OrderIntent
-> Intent execution worker
-> risk checks
-> OMS Order
-> durable BrokerCommand
-> Gateway
-> IBKR paper account
-> broker events
-> fills and reconciliation
```
<!-- automatic-pipeline:end -->

Operator-created orders, broker-imported orders, portfolio-construction
previews, and optimization previews are not alternate automatic strategy
paths. When an approved operator workflow creates an `OrderIntent`, it must
join the same intent execution worker at that boundary.

## Non-negotiable boundaries

Flink owns market-derived computations only.

PostgreSQL owns financial workflow state.

Kafka transports events but is not the financial source of truth.

Strategy plugins never submit broker orders.

The Gateway never decides portfolio allocation or risk.

All automatic orders pass through one common intent execution service.

Consequently:

- Flink may normalize provider data and calculate bars, indicators, and market
  quality. It may not import strategy, allocation, risk, OMS, or Gateway code.
- A Kafka event may wake a Backend consumer, but Kafka offsets and topic
  retention never replace a PostgreSQL workflow record.
- A plugin returns a deterministic decision and target. It may not import OMS,
  risk, the Gateway client, `ib_async`, or any broker adapter.
- Only the Backend owns target aggregation, allocation, rebalancing, sizing,
  risk, OMS state, fills, ledgers, and reconciliation.
- Backend PostgreSQL owns the financial `BrokerCommand` and its relationship to
  OMS state. The Gateway owns a second local durable `GatewayCommand`, the
  single `ib_async` connection, and callback buffering. It accepts
  already-approved order commands and cannot resize, allocate, or approve them.

## Pipeline ownership matrix

Each row has one accountable owner. A component may call supporting libraries,
but that does not transfer ownership.

| Stage | Named owner | Input | Output | Durable records created or updated | Kafka topics |
| --- | --- | --- | --- | --- | --- |
| Market provider | Market Provider Adapter (`IBAsyncBrokerAdapter` or `FinnhubRealtimeWorker`) | Active canonical subscription, qualified contract, provider credentials, provider callbacks/trades | Provider event with canonical subscription identity, provider generation, event time, and stable source event ID | Gateway SQLite: `GatewayEvent` for IBKR callbacks. PostgreSQL: provider health/subscription timestamps through Backend ingestion | None directly |
| `market.raw.v1` | Backend Market Ingestion (`publish_provider_event` plus transactional outbox publisher) | IBKR `market.raw` Gateway event or Finnhub five-second bar | Versioned `market.raw` envelope keyed by instrument | PostgreSQL: `MarketDataSubscription`, `MarketDataProviderTransition` when providers change, `OutboxEvent` | Produces `market.raw.v1`; uses `instrument.registry.v1` separately for canonical mappings |
| Flink normalization | Flink `market-normalization-v2` | `market.raw.v1` plus the keyed instrument registry | Validated, deterministically identified canonical market event, or a deterministic dead letter after bounded unknown-conId buffering | Flink keyed registry/pending state and TTL-bounded deduplication state only; no financial database records | Consumes `market.raw.v1`, `instrument.registry.v1`; produces `market.canonical.v1`, `dead-letter.v1` |
| Flink bars and indicators | Flink Derived Market Jobs (`bar-aggregation-v2`, `indicator-computation-v2`, `stale-price-detection-v1`) | Canonical events, active full-identity `strategy.inputs.v1` requirements, event-time watermarks | Final versioned bars, requirement-identified indicators, freshness/quality events, all carrying processing mode | Flink checkpoint/operator state only; no financial database records | Consumes `market.canonical.v1`, `market.bars.v1`, `strategy.inputs.v1`; produces `market.bars.v1`, `market.indicators.v1`, `market.quality.v1` |
| Kafka derived-market topics | Flink Kafka Sinks | Derived envelopes with deterministic event IDs and causal metadata | Durable transport for Backend consumers | Kafka log only; never financial workflow state | `market.canonical.v1`, `market.bars.v1`, `market.indicators.v1`, `market.quality.v1` |
| Backend market persistence | Backend Market Persistence Consumer (`consume_market_streams`) | Final bar, full-identity indicator, and market-quality envelopes with `LIVE`, `WARMUP`, `REPLAY`, or `BACKFILL` mode | Immutable PostgreSQL market facts; only ordered LIVE facts may update input completeness and create or release a durable evaluation job | PostgreSQL: `ConsumedEvent`, `MarketBar`, `IndicatorValue`, `InstrumentMarketState`, `StrategyEvaluationJob` | Consumes `market.bars.v1`, `market.indicators.v1`, `market.quality.v1` |
| `StrategyEvaluationJob` | Backend Strategy Evaluation Scheduler (`coordinate_bar_readiness` and `ensure_strategy_evaluation_job`) | Persisted final bar/version, current strategy version, and exact expected/available input identities | One durable, claimable job per strategy instance, strategy version, bar ID, and bar version | PostgreSQL: `StrategyEvaluationJob` with unique causal key, status, lease timestamps, bounded attempts, next-attempt time, and classified error | None. Database creation is the workflow handoff |
| Strategy evaluation worker | Backend Strategy Evaluation Worker (`apps.strategies.evaluation_jobs`) | Job claimed with `select_for_update(skip_locked=True)`, immutable strategy version/configuration, persisted bar and indicators | Deterministic strategy decision, signal, optional target, and completed/retry/failed job state | PostgreSQL: `StrategyRun`, `StrategySignal`, `StrategyTarget`, strategy state, `StrategyEvaluationJob`; `OutboxEvent` after commit | Celery queue `strategy_evaluation` wakes the worker; Kafka is not the work queue. May project `strategy.targets.v1` after commit |
| `StrategyTarget` | Backend Strategy Evaluation Worker, using the plugin target contract | Plugin decision in `SHADOW` or `PAPER` mode | Versioned strategy/instrument target with causal run and event IDs | PostgreSQL: `StrategyTarget` | Optional post-commit projection to `strategy.targets.v1` |
| `PortfolioTargetSnapshot` | Backend Target Coordinator (`apps.rebalancing.coordinator`) | Event-time-latest eligible `StrategyTarget` per allocated instance, active strategy versions, lifecycle policy, attributed positions, account/portfolio NAV, cash, positions, active broker orders, reserved intents, prices, reconciliation generation, and causal cut-off | Immutable net portfolio target, constituent attribution, target ages/rejections, projected exposure, and explicit portfolio order/risk policy | PostgreSQL: `PortfolioTargetSnapshot`, `PortfolioTargetCoordination` | Celery queue `target_coordination` wakes a database-backed worker; Kafka delivery is not required |
| `RebalanceRun` | Backend Rebalance Planner | One immutable `PortfolioTargetSnapshot`, persisted positions/prices, `RebalancePolicy`, NAV and available cash | Auditable target positions, drift/cost suppressions, phase and mode | PostgreSQL: `RebalanceRun`, `TargetPortfolioPosition`; `OutboxEvent` | Produces informational `portfolio.rebalance.planned.v1` after commit |
| `OrderIntent` | Backend Rebalance Planner | Unsuppressed PAPER trades from one `RebalanceRun` | Eligible, netted, idempotent intent with strategy-version attribution | PostgreSQL: `OrderIntent`, `OrderIntentAttribution`, `PositionSizingDecision` when configured | None. PostgreSQL is the only intent work queue |
| Intent execution worker | Backend Intent Execution Service (`apps.execution.dispatch`) | Eligible PAPER `OrderIntent` claimed from PostgreSQL | Terminal hold/rejection, or one risk-approved OMS order and one durable PLACE command | PostgreSQL: intent attempt/status, `OperationAttempt`, risk and OMS records, `BrokerCommand` | Celery queue `intent_execution`; never consumes Kafka as authority |
| Risk checks | Backend Pre-Trade Risk Service (`evaluate_intent`) | Locked intent, persisted account/portfolio/strategy policy, sizing decision, kill switches, market freshness, Gateway health, reconciliation state | `APPROVED`, `RESIZED`, `HELD`, or `REJECTED` with approved quantity | PostgreSQL: `RiskCheckResult`, `CapitalReservation`, intent status, `OutboxEvent` | Produces informational `risk.decisions.v1` |
| OMS `Order` | Backend OMS | Approved quantity and exactly one `OrderIntent` | Internal order identity and append-only status transitions | PostgreSQL: `Order`, `OrderStatusHistory`, `OutboxEvent` | Produces informational `orders.events.v1` |
| Durable `BrokerCommand` | Backend Broker Command Dispatcher (`apps.execution.dispatch`) | Risk-approved OMS PLACE, or approved MODIFY/CANCEL request, with stable internal order ID and command idempotency key | Safely claimed dispatch, explicit acknowledgement/retry/failure, or `UNCERTAIN` pending Gateway-and-broker reconciliation | PostgreSQL: `BrokerCommand`; Gateway SQLite after acknowledged handoff: `GatewayCommand`, later `GatewayCommandAttempt` and `GatewayOrderReference` | Celery queue `broker_commands`; Kafka is not the command queue |
| Gateway | Gateway Broker Worker (`broker_worker`) | Claimed `GatewayCommand` | One broker API call or an explicitly `UNKNOWN` outcome; durable callback events | Gateway SQLite: command attempt/result and `GatewayEvent`; no portfolio or risk records | None |
| IBKR paper account | IBKR paper brokerage | Qualified contract and approved broker order | Broker acknowledgement, status, execution and account snapshots | External broker system | None |
| Broker events | Gateway Broker Event Capture | `ib_async` callbacks and periodic snapshots | Ordered, idempotent Gateway events consumed through a per-session Backend cursor | Gateway SQLite: `GatewayEvent`; PostgreSQL: `BrokerSyncCursor`, broker IDs/status history, `BrokerPositionSnapshot` | Backend may project order/execution events only after PostgreSQL commit |
| Fills and reconciliation | Backend Broker Accounting Boundary (`broker_gateway.sync`, OMS fill accounting, and Reconciliation Service) | Ordered Gateway broker events/snapshots and persisted OMS state | Idempotent fills, ledgers, positions, reservation settlement, reconciliation result and breaks | PostgreSQL: `Fill`, `CashLedgerEntry`, `PositionLedgerEntry`, `PortfolioPosition`, `StrategyAttributedPosition`, `ReconciliationRun`, `ReconciliationBreak`, `OutboxEvent` | Produces informational `executions.events.v1` and `reconciliation.events.v1` |

## Workflow handoffs and transaction boundaries

The automatic path uses database handoffs after derived market persistence.
Kafka is deliberately absent as an authoritative trigger between
`StrategyEvaluationJob` and broker submission.

1. Provider ingestion validates subscription, contract, active provider, and
   provider generation inside a PostgreSQL transaction. It writes
   `OutboxEvent`; the outbox publisher retries Kafka delivery independently.
2. Flink derives canonical events, bars, indicators, and quality only. Stable
   UUIDv5 event IDs exclude processing time and Kafka position. Indicator
   identity includes name, role, parameters, instrument, timeframe, and
   implementation version. Keyed conId buffering protects registry startup
   order, and deduplication state has a configured TTL.
3. The market persistence consumer writes the market fact, readiness, durable
   `StrategyEvaluationJob`, and `ConsumedEvent` atomically. It commits the
   Kafka offset only after that PostgreSQL transaction commits. A job can wait
   durably for missing indicators; the consumer never imports or executes a
   strategy plugin, so plugin failure cannot dead-letter a valid market event.
4. Before a LIVE job is made executable, the scheduler locks the strategy and
   compares event time, bar ID, and version with its last accepted market
   cursor. Older LIVE facts are quarantined. WARMUP, REPLAY, and BACKFILL facts
   cannot schedule evaluation or change live strategy state. Backend Kafka
   replay tooling overwrites the persisted envelope mode to `REPLAY` before
   invoking any market handler.
5. The evaluation worker claims the job with a PostgreSQL row lock and
   `skip_locked`. Plugin evaluation and
   `StrategyRun`/`StrategySignal`/`StrategyTarget` writes occur in the job's
   financial transaction. Any Kafka projection is an outbox side effect after
   commit.
6. Target aggregation snapshots a causal set once. The rebalancer consumes
   that immutable snapshot; it must never query a moving set of "latest"
   targets while planning.
7. PAPER planning persists `OrderIntent`. No planner, plugin, API view, Kafka
   consumer, or Flink job may submit it directly.
8. The intent execution worker claims the intent, runs all risk checks, creates
   at most one OMS `Order`, and atomically creates one PostgreSQL
   `BrokerCommand`. No unsafe Gateway call occurs in that transaction.
9. The broker-command dispatcher claims with
   `select_for_update(skip_locked=True)`, repeats the kill-switch and
   reconciliation gates, marks `SENDING`, and calls the portfolio's bound
   Gateway outside the database transaction. A transport timeout becomes
   `UNCERTAIN`, never a blind retry.
10. The Gateway persists `GatewayCommand` before acknowledging the request.
   Its sole broker worker owns `ib_async` and the TWS socket. IBKR receives the
   immutable OMS internal order ID as `orderRef`.
11. For an uncertain PLACE, the dispatcher queries the Gateway command ledger,
   Gateway order reference, and open/completed broker snapshots by internal
   order ID. It attaches an existing order when present, accepts an already
   durable Gateway command, or retries only when the Gateway explicitly proves
   that neither command nor broker order exists.
12. Broker callbacks are first durable `GatewayEvent` records. Backend advances
   a per-session `BrokerSyncCursor` only after each event is projected.
   Execution callbacks, not status callbacks, create fills and ledgers.
13. Reconciliation compares the IBKR paper account with PostgreSQL and blocks
    new risk approval while material breaks remain open.

## Retry and idempotency matrix

| Boundary | Idempotency identity | Retry rule | Ambiguous-outcome rule |
| --- | --- | --- | --- |
| Provider -> Backend outbox | Bar: instrument + timeframe + window; tick: instrument + source event ID | Retry publication from `OutboxEvent` with backoff | A repeated provider event resolves to the existing outbox row |
| Kafka -> Flink | UUIDv5 over canonical raw/canonical/bar/indicator/quality identities plus keyed Flink state/checkpoint | Normal jobs resume committed offsets and use latest only when a new group has no commit; job-specific earliest/latest overrides support controlled replay. Unknown conIds wait in bounded keyed state before DLQ | Checkpoint replay produces the same IDs; TTL-bounded deduplication and Backend `ConsumedEvent` suppress duplicate effects |
| Derived topic -> market persistence | `ConsumedEvent(consumer_name, event_id)` plus bar/indicator unique constraints | Failed consumption stays visible and is replayed explicitly from dead letter | Never infer completion from a committed offset alone |
| Market persistence -> `StrategyEvaluationJob` | Unique constraint: strategy instance + strategy version + bar ID + bar version; separate unique idempotency key | Duplicate events update the same market/readiness identity. Missing-input jobs wait; corrected readiness promotes them once | A completed or terminal job is never reactivated by an event replay |
| Evaluation job -> `StrategyRun` | Existing strategy idempotency key includes instance, version, instrument, timeframe, source event, and data version | Only infrastructure failures retry, using bounded exponential backoff. Expired `CLAIMED`/`RUNNING` leases recover through the same attempt bound | Plugin, stale-input, invalid-configuration, and data-integrity failures are terminal; plugin failure cannot create or submit an order |
| Targets -> `PortfolioTargetSnapshot` | Content hash over the causal cut-off, contributing target/version set, positions, orders, reservations, prices, account state, lifecycle decisions, and policy | The coordinator debounces durable portfolio marks. Rebuild only as a new snapshot; snapshot rows reject updates | A `RebalanceRun` retains its exact snapshot ID and embedded planning inputs |
| Snapshot -> `RebalanceRun` | Unique `RebalanceRun.idempotency_key` plus canonical request hash | Stored retryable failures require explicit retry | Same key with different inputs is a conflict |
| `RebalanceRun` -> `OrderIntent` | Rebalance + instrument + planning version; unique intent key | Recovery may recreate only a provably missing intent with a new recovery version | Existing intent/order is reused, never duplicated |
| Intent worker -> risk/OMS/command | Claimed intent attempt; one-to-one `Order.intent`; unique PLACE command key | `HELD` is reevaluated deliberately; rejection is terminal unless policy defines a new intent | Existing OMS order and command rows prevent duplicate creation |
| Backend `BrokerCommand` -> Gateway | Unique command key plus request hash, scoped by the bound Gateway session; PLACE always carries internal OMS order ID | Pre-send routing/health holds use bounded backoff; recovered `CLAIMED` is safe to reclaim | `SENDING` lease expiry or HTTP timeout becomes `UNCERTAIN`; Gateway command/reference and broker state must reconcile before retry |
| Gateway -> IBKR | Durable `GatewayCommand`, attempt lease, internal order ID in IBKR `orderRef` | Expired pre-submission lease may be reclaimed | Post-submission uncertainty becomes `UNKNOWN` until broker lookup/reconciliation |
| Broker event -> fill/ledger | Gateway event key, Backend sync cursor, broker execution ID, ledger idempotency keys | Reprocessing is safe. A later commission callback updates the existing fill, cash ledger, and attribution cost without replaying position quantity | Status alone never manufactures a fill |
| Reconciliation | Account + Gateway session + broker snapshot/run | Scheduled and operator runs may repeat | Material breaks keep the account unreconciled and block new approval |

## Execution modes

| Mode | Evaluation and records | Furthest permitted automatic stage | Broker effect |
| --- | --- | --- | --- |
| `OBSERVE` | Persist evaluation job/run and signal; do not create a `StrategyTarget` | Strategy evaluation worker | None |
| `SHADOW` | Create `StrategyTarget`, `PortfolioTargetSnapshot`, `RebalanceRun`, and target-position plan | `RebalanceRun` plan | No `OrderIntent`, OMS order, BrokerCommand, or broker call |
| `PAPER` | Execute the complete documented path with normal sizing, risk, OMS, command durability, fills, ledgers, and reconciliation | IBKR paper account and reconciliation | Paper orders only |

`LIVE` is not a supported automatic execution mode. Mode gates may stop a
pipeline early, but they may not bypass a stage.

## Current implementation and cutover

The complete documented PAPER path now has a durable database handoff at every
financial boundary. The manual order API uses the same intent service, while
automatic PAPER intents are claimed by its Celery worker.

Planned delivery phases:

- **Completed - durable evaluation cutover:** `StrategyEvaluationJob`, the
  dedicated worker/queue, failure classification, bounded retry, and stuck-job
  recovery now isolate market persistence from plugin execution.
- **Completed - portfolio target coordination:** strategy completion marks
  durable portfolio state; the debounced `target_coordination` worker locks the
  portfolio, selects targets by event time and active version, freezes projected
  exposure in `PortfolioTargetSnapshot`, and permits one active automatic
  `RebalanceRun`.
- **Completed - durable execution cutover:** the common intent service creates
  risk/OMS state and a PostgreSQL `BrokerCommand`; the dedicated dispatcher
  owns all PLACE/MODIFY/CANCEL Gateway calls, uncertainty reconciliation, and
  stuck-command recovery.
- **Completed - end-to-end validation and legacy removal:** deterministic
  market replay, every durable worker handoff, broker uncertainty, callback
  idempotency, late commissions, accounting, and reconciliation are exercised
  by one PAPER pipeline test. Fully superseded entry points are removed.

## Legacy candidates and completed removals

| File path | Function or class | Why it is a legacy or duplicate entry point | Replacement owner | Planned deletion phase |
| --- | --- | --- | --- | --- |
| `Backend/apps/market_streams/models.py` | `StrategyEvaluationReadiness` (**removed**) | It duplicated input and execution status already durably represented by `StrategyEvaluationJob` | Backend Strategy Evaluation Scheduler (`StrategyEvaluationJob`) | Completed after restart and delayed-input tests; a new migration removes the obsolete table without editing historical migrations |
| `Backend/apps/market_streams/services.py` | `record_indicator_readiness` and `evaluate_ready_strategies` (**removed**) | These compatibility helpers carried the old parameter-hash readiness boundary. Persistence now invokes full-identity `coordinate_bar_readiness` directly | Backend Strategy Evaluation Scheduler | Completed during deterministic streaming cutover |
| `Backend/apps/strategies/views.py` | `action(..., action_name="evaluate")` inline call to `evaluate_instance` (**removed**) | Operator evaluation executed in the request process rather than creating the same durable evaluation job | Backend Strategy Evaluation Scheduler and Strategy Evaluation Worker | Completed after the durable job path was verified |
| `Backend/apps/rebalancing/services.py` | `aggregate_targets` (**removed**) and the former moving-target branch of `plan_rebalance` (**replaced**) | Planning previously read a moving "latest target" set | Backend Target Coordinator | Completed after snapshot/coordinator tests |
| `Backend/apps/allocation/services.py` | `aggregate_targets`, `create_rebalance` (**removed**) | Compatibility aliases exposed a second target/rebalance entry point and hard-coded PAPER behaviour | Backend Target Coordinator and Rebalance Planner | Completed after snapshot/coordinator tests |
| `Backend/apps/core/views.py` | Former inline `orders` POST/PATCH/cancel Gateway calls (**removed**) | The view previously coupled API availability, risk/OMS mutation, and unsafe Gateway I/O | Backend Intent Execution Service and Broker Command Dispatcher | Completed during durable command cutover |
| `Backend/apps/rebalancing/services.py` | Intent-synthesis branch in `recover_incomplete` (**removed**) | Recovery could create a new economic intent from moving positions instead of resuming the immutable snapshot workflow | Target Coordinator and common Intent Execution Service | Completed after coordinator and intent-worker restart tests; recovery now advances stored runs only |

The following similarly named paths are not legacy automatic submission
entries:

- `GatewayClient.place_order`, `modify_order`, and `cancel_order` are
  authenticated Backend-to-Gateway transports and remain callable only by the
  Broker Command Dispatcher.
- Gateway `orders`/`enqueue`, `GatewayCommand`, and `broker_worker` are the
  required durable command and sole broker-connection boundary.
- `_external_order` in `broker_gateway.sync` imports an order already found at
  IBKR for accounting and reconciliation; it never submits one.
- Portfolio optimization and construction can create operator-approved
  rebalance plans, but any resulting PAPER `OrderIntent` must use the same
  common intent execution service.
- Strategy flatten is an explicit operator action that may create a target; it
  cannot submit an order and must proceed through snapshot, rebalance, and the
  common intent service.

## Target coordination policy

The coordinator serializes automatic work with a `TradingPortfolio` row lock
and a conditional database uniqueness constraint on active automatic
rebalances. A target arriving during `QUEUED`, `CALCULATING`,
`INTENTS_CREATED`, or `EXECUTING` marks `pending_recalculation`; it cannot open
a concurrent run. Terminal order handling releases the active run and makes
the pending portfolio immediately eligible for another snapshot.

Selection uses target event time, then record creation time and primary key as
deterministic tie-breakers. A target is rejected if it is expired, stale, or
does not reference the instance's active immutable version. Any such rejection
makes that snapshot non-executable. Strategy lifecycle policy is explicit:

- `PAUSED` retains strategy-attributed exposure unless its risk-policy
  configuration says `FLATTEN`.
- `DISABLED` makes no new decision and retains attributed exposure by default.
- `FLATTEN_REQUESTED` contributes zero.
- `KILLED` stops new decisions and uses configured `killed_behavior`, defaulting
  to `HOLD`.
- `ERROR` uses configured `error_behavior`, defaulting to `HOLD`.

For every instrument, projected quantity is:

```text
filled quantity
+ remaining signed active broker orders
+ reserved signed order intents that do not already have an active broker order
```

The rebalance compares target quantity with that projected quantity. Individual
strategy targets are checked against their own strategy risk policy before
aggregation. The net order is checked against portfolio order quantity,
notional, cash, turnover, and drift limits. When multiple strategies
contribute, the order policy belonging to the lowest-priority-number
`StrategyAllocation` wins, with strategy ID as the deterministic tie-breaker;
that choice is stored in the immutable snapshot.

Every PAPER strategy also registers a framework-owned `average_volume`
requirement. Flink computes it like any other full-identity market input, while
the strategy plugin may ignore it. The Rebalance Planner freezes that value in
its sizing decision so the risk service can enforce participation limits; a
missing value cannot silently disable the liquidity bound.

## Automatic execution readiness

`GET /api/v1/execution/readiness/` is the fail-closed readiness surface for
automatic PAPER execution. It does not replace `/healthz` process liveness or
general `/readyz` application readiness. Its response names every signal,
threshold, age, and blocker used in the decision.

The report includes:

- the `market.raw.v1` producer heartbeat and Backend market-consumer heartbeat;
- the exact required Flink job set and latest completed checkpoint per job;
- strategy-evaluation and target-coordination backlog counts and oldest ages;
- active automatic rebalances, pending intent age, and broker-command age;
- dedicated strategy, target, intent, and broker-dispatch worker heartbeats;
- the portfolio-bound Gateway connection and account reconciliation state; and
- unresolved `UNCERTAIN` broker commands, grouped by affected portfolio.

Automatic execution readiness is false if a required Flink job or checkpoint
is missing/stale, required market data or a producer/consumer heartbeat is
stale, the strategy backlog exceeds its threshold, a required worker is
missing/stale, a PAPER portfolio Gateway or account is not reconciled, or an
uncertain command blocks a portfolio. Target, intent, and command backlog ages
are reported and become blockers at their configured limits. An active
rebalance is reported but is not itself a readiness failure because the
portfolio lock and active-run uniqueness constraint serialize it.

## End-to-end validation

The integration test
`Backend/tests/test_automatic_execution_e2e.py` drives synthetic provider facts
through the deterministic Kafka/Flink envelope functions and every PostgreSQL
workflow boundary, then uses a mock Gateway response and broker callback to
prove exactly one strategy run, portfolio decision, approved order, broker
submission, fill, ledger application, and clean reconciliation. Its
failure-injection cases cover replay or worker loss at every major handoff,
lost Gateway responses, duplicate callbacks, and commission arrival after the
fill.

Run the complete local validation from the repository root:

```powershell
powershell -NoProfile -File docs\automatic_execution_smoke.ps1
```

Each smoke failure is prefixed with the exact broken stage. Use
`-SkipInfrastructure` only when Kafka/Flink/consumer process validation was
already completed and only the architecture and isolated PAPER pipeline need
to be rerun.

## Architecture verification

Run the non-behavioural ownership check from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\check_execution_architecture.py
```

The check verifies the single ordered automatic path, mandatory ownership
statements, documented legacy submission site, strategy-plugin isolation, and
that market persistence schedules durable jobs without calling plugins.
