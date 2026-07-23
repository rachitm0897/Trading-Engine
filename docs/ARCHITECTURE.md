# Automatic strategy execution architecture

## Status and scope

This document is the ownership contract for automatic strategy execution.
Durable strategy evaluation is implemented; components still labelled
**planned** do not exist yet. The evaluation cutover changes process ownership
and failure isolation, not strategy decisions, target semantics, risk, sizing,
OMS, Gateway, or broker behaviour.

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
- Only the Gateway owns durable broker commands, the single `ib_async`
  connection, and callback buffering. It accepts already-approved order
  commands and cannot resize, allocate, or approve them.

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
| Backend market persistence | Backend Market Persistence Consumer (`consume_market_streams`) | Final bar, full-identity indicator, and market-quality envelopes with `LIVE`, `WARMUP`, `REPLAY`, or `BACKFILL` mode | Immutable PostgreSQL market facts; only ordered LIVE facts may update readiness and create a durable evaluation job | PostgreSQL: `ConsumedEvent`, `MarketBar`, `IndicatorValue`, `InstrumentMarketState`, `StrategyEvaluationReadiness`, `StrategyEvaluationJob` | Consumes `market.bars.v1`, `market.indicators.v1`, `market.quality.v1` |
| `StrategyEvaluationJob` | Backend Strategy Evaluation Scheduler (`coordinate_bar_readiness` and `ensure_strategy_evaluation_job`) | Persisted final bar/version, current strategy version, and exact expected/available input identities | One durable, claimable job per strategy instance, strategy version, bar ID, and bar version | PostgreSQL: `StrategyEvaluationJob` with unique causal key, status, lease timestamps, bounded attempts, next-attempt time, and classified error | None. Database creation is the workflow handoff |
| Strategy evaluation worker | Backend Strategy Evaluation Worker (`apps.strategies.evaluation_jobs`) | Job claimed with `select_for_update(skip_locked=True)`, immutable strategy version/configuration, persisted bar and indicators | Deterministic strategy decision, signal, optional target, and completed/retry/failed job state | PostgreSQL: `StrategyRun`, `StrategySignal`, `StrategyTarget`, strategy state, `StrategyEvaluationJob`; `OutboxEvent` after commit | Celery queue `strategy_evaluation` wakes the worker; Kafka is not the work queue. May project `strategy.targets.v1` after commit |
| `StrategyTarget` | Backend Strategy Evaluation Worker, using the plugin target contract | Plugin decision in `SHADOW` or `PAPER` mode | Versioned strategy/instrument target with causal run and event IDs | PostgreSQL: `StrategyTarget` | Optional post-commit projection to `strategy.targets.v1` |
| `PortfolioTargetSnapshot` (**planned**) | Backend Portfolio Target Aggregation Service | Latest eligible `StrategyTarget` per enabled instance, `StrategyAllocation`, portfolio NAV, strategy versions, and causal cut-off | Immutable net portfolio target plus constituent attribution | PostgreSQL: planned `PortfolioTargetSnapshot` and constituent rows | None required. An informational outbox projection may be added after the database commit |
| `RebalanceRun` | Backend Rebalance Planner | One immutable `PortfolioTargetSnapshot`, persisted positions/prices, `RebalancePolicy`, NAV and available cash | Auditable target positions, drift/cost suppressions, phase and mode | PostgreSQL: `RebalanceRun`, `TargetPortfolioPosition`; `OutboxEvent` | Produces informational `portfolio.rebalance.planned.v1` after commit |
| `OrderIntent` | Backend Rebalance Planner | Unsuppressed PAPER trades from one `RebalanceRun` | Eligible, netted, idempotent intent with strategy-version attribution | PostgreSQL: `OrderIntent`, `OrderIntentAttribution`, `PositionSizingDecision` when configured | `order.intents.v1` is an optional projection only; it is not the work queue |
| Intent execution worker (**planned**) | Backend Intent Execution Service | Eligible PAPER `OrderIntent` claimed from PostgreSQL | Terminal hold/rejection, or one risk-approved OMS order followed by one Gateway command request | PostgreSQL: intent attempt/status, `OperationAttempt`, risk and OMS records; stores returned Gateway command identity | May project intent/order status after commit; never consumes Kafka as authority |
| Risk checks | Backend Pre-Trade Risk Service (`evaluate_intent`) | Locked intent, persisted account/portfolio/strategy policy, sizing decision, kill switches, market freshness, Gateway health, reconciliation state | `APPROVED`, `RESIZED`, `HELD`, or `REJECTED` with approved quantity | PostgreSQL: `RiskCheckResult`, `CapitalReservation`, intent status, `OutboxEvent` | Produces informational `risk.decisions.v1` |
| OMS `Order` | Backend OMS | Approved quantity and exactly one `OrderIntent` | Internal order identity and append-only status transitions | PostgreSQL: `Order`, `OrderStatusHistory`, `OutboxEvent` | Produces informational `orders.events.v1` |
| Durable `BrokerCommand` | Gateway Command API (concrete record: `GatewayCommand`) | Authenticated, risk-approved order payload with internal OMS order ID and idempotency key | Durable `PENDING` command acknowledged to Backend before broker I/O | Gateway SQLite: `GatewayCommand`, later `GatewayCommandAttempt` and `GatewayOrderReference` | None |
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
8. The intent execution worker claims the intent, runs all risk checks,
   creates at most one OMS `Order`, and asks the Gateway to durably enqueue one
   command. Network I/O is outside PostgreSQL transactions.
9. The Gateway persists `GatewayCommand` before acknowledging the request.
   Its sole broker worker owns `ib_async` and the TWS socket.
10. Broker callbacks are first durable `GatewayEvent` records. Backend advances
   a per-session `BrokerSyncCursor` only after each event is projected.
   Execution callbacks, not status callbacks, create fills and ledgers.
11. Reconciliation compares the IBKR paper account with PostgreSQL and blocks
    new risk approval while material breaks remain open.

## Retry and idempotency matrix

| Boundary | Idempotency identity | Retry rule | Ambiguous-outcome rule |
| --- | --- | --- | --- |
| Provider -> Backend outbox | Bar: instrument + timeframe + window; tick: instrument + source event ID | Retry publication from `OutboxEvent` with backoff | A repeated provider event resolves to the existing outbox row |
| Kafka -> Flink | UUIDv5 over canonical raw/canonical/bar/indicator/quality identities plus keyed Flink state/checkpoint | Normal jobs resume committed offsets and use latest only when a new group has no commit; job-specific earliest/latest overrides support controlled replay. Unknown conIds wait in bounded keyed state before DLQ | Checkpoint replay produces the same IDs; TTL-bounded deduplication and Backend `ConsumedEvent` suppress duplicate effects |
| Derived topic -> market persistence | `ConsumedEvent(consumer_name, event_id)` plus bar/indicator unique constraints | Failed consumption stays visible and is replayed explicitly from dead letter | Never infer completion from a committed offset alone |
| Market persistence -> `StrategyEvaluationJob` | Unique constraint: strategy instance + strategy version + bar ID + bar version; separate unique idempotency key | Duplicate events update the same market/readiness identity. Missing-input jobs wait; corrected readiness promotes them once | A completed or terminal job is never reactivated by an event replay |
| Evaluation job -> `StrategyRun` | Existing strategy idempotency key includes instance, version, instrument, timeframe, source event, and data version | Only infrastructure failures retry, using bounded exponential backoff. Expired `CLAIMED`/`RUNNING` leases recover through the same attempt bound | Plugin, stale-input, invalid-configuration, and data-integrity failures are terminal; plugin failure cannot create or submit an order |
| Targets -> `PortfolioTargetSnapshot` | Planned unique causal cut-off per portfolio and contributing target/version set | Rebuild only as a new snapshot, never mutate a consumed snapshot | A `RebalanceRun` always retains its exact snapshot identity |
| Snapshot -> `RebalanceRun` | Unique `RebalanceRun.idempotency_key` plus canonical request hash | Stored retryable failures require explicit retry | Same key with different inputs is a conflict |
| `RebalanceRun` -> `OrderIntent` | Rebalance + instrument + planning version; unique intent key | Recovery may recreate only a provably missing intent with a new recovery version | Existing intent/order is reused, never duplicated |
| Intent worker -> risk/OMS | Claimed intent attempt; one-to-one `Order.intent` | `HELD` is reevaluated deliberately; rejection is terminal unless policy defines a new intent | An existing OMS order prevents a second order |
| Backend -> Gateway | `gateway:place:<internal OMS order id>` scoped to Gateway session, plus request hash | Retry only when the Gateway reports a stored retryable pre-submission failure | Timeout/unknown submission is reconciled by internal order ID; it is not blindly resubmitted |
| Gateway -> IBKR | Durable `GatewayCommand`, attempt lease, internal order ID in IBKR `orderRef` | Expired pre-submission lease may be reclaimed | Post-submission uncertainty becomes `UNKNOWN` until broker lookup/reconciliation |
| Broker event -> fill/ledger | Gateway event key, Backend sync cursor, broker execution ID, ledger idempotency keys | Reprocessing is safe | Status alone never manufactures a fill |
| Reconciliation | Account + Gateway session + broker snapshot/run | Scheduled and operator runs may repeat | Material breaks keep the account unreconciled and block new approval |

## Execution modes

| Mode | Evaluation and records | Furthest permitted automatic stage | Broker effect |
| --- | --- | --- | --- |
| `OBSERVE` | Persist evaluation job/run and signal; do not create a `StrategyTarget` | Strategy evaluation worker | None |
| `SHADOW` | Create `StrategyTarget`, `PortfolioTargetSnapshot`, `RebalanceRun`, and target-position plan | `RebalanceRun` plan | No `OrderIntent`, OMS order, BrokerCommand, or broker call |
| `PAPER` | Execute the complete documented path with normal sizing, risk, OMS, command durability, fills, ledgers, and reconciliation | IBKR paper account and reconciliation | Paper orders only |

`LIVE` is not a supported automatic execution mode. Mode gates may stop a
pipeline early, but they may not bypass a stage.

## Current implementation and planned cutover

The target boundaries above are intentionally ahead of the current code in
two places:

| Gap | Current implementation | Required replacement |
| --- | --- | --- |
| Immutable portfolio target | `aggregate_targets` dynamically reads the latest target while `plan_rebalance` is running | Add `PortfolioTargetSnapshot` with constituent attribution; require its ID on the automatic strategy rebalance path |
| Common intent execution | PAPER rebalancing persists intents, but the complete risk/OMS/Gateway orchestration exists inline only in the manual orders API | Add one Intent Execution Service/worker and route every automatic intent through it; the manual API should enqueue an intent into the same service |

Planned delivery phases:

- **Completed - durable evaluation cutover:** `StrategyEvaluationJob`, the
  dedicated worker/queue, failure classification, bounded retry, and stuck-job
  recovery now isolate market persistence from plugin execution.
- **Phase 3 - remaining workers and shadow cutover:** implement the target
  snapshot service and common intent execution service; compare legacy and new
  results in OBSERVE/SHADOW before PAPER is enabled.
- **Phase 4 - legacy removal:** after parity, restart, retry, and paper-broker
  verification, remove the candidates below and their compatibility tests.

## Legacy candidates: retain until replacement is verified

No candidate is deleted in this phase.

| File path | Function or class | Why it is a legacy or duplicate entry point | Replacement owner | Planned deletion phase |
| --- | --- | --- | --- | --- |
| `Backend/apps/market_streams/models.py` | `StrategyEvaluationReadiness` | It remains a compatibility/input-completeness record; leases, attempts, execution status, and errors now belong to `StrategyEvaluationJob` | Backend Strategy Evaluation Scheduler (`StrategyEvaluationJob`) | Phase 4, after readiness can be derived without compatibility callers |
| `Backend/apps/market_streams/services.py` | `record_indicator_readiness` and `evaluate_ready_strategies` (**removed**) | These compatibility helpers carried the old parameter-hash readiness boundary. Persistence now invokes full-identity `coordinate_bar_readiness` directly | Backend Strategy Evaluation Scheduler | Completed during deterministic streaming cutover |
| `Backend/apps/strategies/views.py` | `action(..., action_name="evaluate")` inline call to `evaluate_instance` | Operator evaluation executes in the request process rather than creating the same durable evaluation job | Backend Strategy Evaluation Scheduler and Strategy Evaluation Worker | Phase 4 |
| `Backend/apps/rebalancing/services.py` | `aggregate_targets` and the no-explicit-target-source branch of `plan_rebalance` | Planning reads a moving "latest target" set and skips an immutable `PortfolioTargetSnapshot` | Backend Portfolio Target Aggregation Service | Phase 3 cutover; delete in Phase 4 |
| `Backend/apps/allocation/services.py` | `aggregate_targets`, `create_rebalance` | Compatibility aliases expose a second target/rebalance entry point and hard-code PAPER behaviour | Backend Portfolio Target Aggregation Service and Rebalance Planner | Phase 4 |
| `Backend/apps/core/views.py` | `orders` POST branch (`evaluate_intent` -> `create_order` -> `GatewayClient.place_order`) | Risk, OMS creation, and Gateway submission are orchestrated inline in an HTTP request instead of by the common intent service | Backend Intent Execution Service | Phase 3 cutover; delete inline orchestration in Phase 4 |

The following similarly named paths are not legacy automatic submission
entries:

- `GatewayClient.place_order` is the authenticated Backend-to-Gateway
  transport and remains behind the common intent service.
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

## Architecture verification

Run the non-behavioural ownership check from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\check_execution_architecture.py
```

The check verifies the single ordered automatic path, mandatory ownership
statements, documented legacy submission site, strategy-plugin isolation, and
that market persistence schedules durable jobs without calling plugins.
