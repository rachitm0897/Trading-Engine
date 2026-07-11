# Kafka, Flink, Rebalancing and Allocation
## Incremental Implementation Plan

## 1. Goal

Extend the already implemented IBKR trading engine. Preserve the current:

- `Backend/`
- `Frontend/`
- `IB_gateway/`
- risk engine;
- OMS;
- execution ledger;
- reconciliation flow;
- one-public-port rule for each application.

Add:

1. Kafka as the durable event bus.
2. PyFlink for continuous market normalization, bar generation, indicators and stale-data detection.
3. Portfolio rebalancing.
4. Deposit and withdrawal flow allocation.
5. Single-stock allocation and position sizing.
6. Frontend and operational visibility for all new workflows.

Kafka and Flink must never place broker orders. PostgreSQL remains the source of truth for orders, fills, cash, positions, risk decisions and reconciliation.

---

## 2. Target Architecture

```text
IBKR / market source
        |
        v
market.raw.v1
        |
        v
Flink normalization and event-time processing
        |
        +--> market.canonical.v1
        +--> market.bars.v1
        +--> market.indicators.v1
        +--> market.quality.v1
        |
        v
Backend strategy engine
        |
        v
strategy.targets.v1
        |
        v
Allocation and rebalancing
        |
        v
OrderIntent
        |
        v
Position sizing and risk
        |
        v
OMS -> IB_gateway -> IBKR
        |
        v
Executions, ledgers and reconciliation
```

Technology ownership:

| Component | Responsibility |
|---|---|
| PostgreSQL | Authoritative business and financial state |
| Kafka | Durable event transport and replay |
| Flink | Stateful streaming calculations |
| Redis | Celery, short-lived locks and cache |
| Celery/Beat | Scheduled business workflows |
| IB_gateway | Sole IBKR connection owner |

---

## 3. Repository Changes

Keep the three current application folders.

Add:

```text
streaming/
├── flink/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── jobs/
│   │   ├── market_normalization.py
│   │   ├── bar_aggregation.py
│   │   ├── indicator_computation.py
│   │   ├── stale_price_detection.py
│   │   └── stream_health.py
│   └── tests/
├── kafka/
│   ├── topics.yml
│   ├── schemas/
│   └── README.md
└── README.md
```

Add or complete Backend modules:

```text
event_bus
market_streams
allocation
rebalancing
position_sizing
```

Extend local `docker-compose.yml` with:

```text
kafka
flink-jobmanager
flink-taskmanager
```

Kafka and Flink are internal infrastructure. Do not add a fourth public application or expose them publicly in production.

---

## 4. Kafka Design

### Topics

```text
market.raw.v1
market.canonical.v1
market.bars.v1
market.indicators.v1
market.quality.v1

strategy.run.requested.v1
strategy.run.completed.v1
strategy.targets.v1

portfolio.flow.requested.v1
portfolio.flow.allocated.v1
portfolio.rebalance.requested.v1
portfolio.rebalance.planned.v1
portfolio.rebalance.completed.v1

order.intents.v1
risk.decisions.v1
orders.events.v1
executions.events.v1
reconciliation.events.v1

system.health.v1
dead-letter.v1
```

Partition keys:

- market topics: `instrument_id`;
- strategy topics: `strategy_id` or `portfolio_id`;
- portfolio topics: `portfolio_id`;
- order topics: `internal_order_id`;
- execution and reconciliation topics: `account_id`.

### Event envelope

Use versioned JSON Schema:

```json
{
  "event_id": "uuid",
  "event_type": "portfolio.rebalance.planned",
  "schema_version": 1,
  "occurred_at": "UTC timestamp",
  "produced_at": "UTC timestamp",
  "producer": "backend",
  "aggregate_type": "portfolio",
  "aggregate_id": "uuid",
  "correlation_id": "uuid",
  "causation_id": "uuid",
  "idempotency_key": "string",
  "payload": {}
}
```

Rules:

- immutable business facts only;
- decimals serialized as strings;
- UTC timestamps;
- no credentials or secrets;
- stable IDs across retries;
- breaking schema changes require a new version.

---

## 5. Transactional Outbox and Idempotency

Use PostgreSQL transactional outbox.

`OutboxEvent` fields:

```text
event_id
topic
partition_key
event_type
schema_version
payload
correlation_id
causation_id
idempotency_key
status
attempt_count
available_at
published_at
last_error
created_at
```

Publisher workflow:

1. update business state;
2. insert outbox row in the same transaction;
3. commit PostgreSQL;
4. publish with a dedicated worker;
5. mark published only after Kafka acknowledgement;
6. retry with exponential backoff.

Use `SELECT FOR UPDATE SKIP LOCKED` for concurrent publishers.

Add `ConsumedEvent`:

```text
consumer_name
event_id
processed_at
result
```

Consumer workflow:

1. begin PostgreSQL transaction;
2. reject already consumed event IDs;
3. apply business changes;
4. insert `ConsumedEvent`;
5. commit;
6. acknowledge Kafka offset.

This must protect flows, rebalances, fills and order intents from duplicate processing.

---

## 6. Flink Jobs

Use PyFlink and stable operator IDs.

### Market normalization

Input:

```text
market.raw.v1
```

Responsibilities:

- map source symbols to canonical instruments;
- normalize timestamps, exchange, currency, price and volume;
- deduplicate stable source event IDs;
- validate positive prices and valid quantities;
- classify late or malformed events;
- emit invalid data to `dead-letter.v1`.

Outputs:

```text
market.canonical.v1
market.quality.v1
dead-letter.v1
```

### Bar aggregation

Input:

```text
market.canonical.v1
```

Generate event-time OHLCV bars for configured windows such as:

```text
1 minute
5 minutes
1 day
```

Requirements:

- watermarks;
- allowed lateness;
- deterministic bar IDs;
- versioned corrected bars;
- final/non-final flag.

Output:

```text
market.bars.v1
```

### Indicators

Input:

```text
market.bars.v1
```

Calculate only what current strategies need:

- fast and slow SMA;
- RSI;
- Donchian upper and lower channel;
- momentum;
- realized volatility;
- rolling average daily volume;
- latest reference price.

Output:

```text
market.indicators.v1
```

### Stale-price detection

Track latest event time per instrument and produce:

```text
FRESH
STALE
UNAVAILABLE
```

Output:

```text
market.quality.v1
```

Risk must reject orders that depend on stale or unavailable prices.

### Recovery

Enable:

- durable checkpoints;
- savepoints for upgrades;
- stable job and operator names;
- configured restart strategy;
- recovery tests for JobManager and TaskManager restarts.

---

## 7. Backend Market Persistence

Consume and persist:

```text
MarketBar
IndicatorValue
InstrumentMarketState
```

Important constraints:

- unique source/bar version keys;
- replay must not duplicate rows;
- strategy calculations should use final bars by default;
- order sizing must use an auditable persisted price;
- indicator records must include parameter versions.

---

## 8. Flow Allocation

### Models

```text
StrategyAllocation
StrategyCapitalSnapshot
PortfolioFlow
AllocationRun
AllocationDecision
```

`PortfolioFlow` types:

```text
DEPOSIT
WITHDRAWAL
INTERNAL_TRANSFER_IN
INTERNAL_TRANSFER_OUT
```

### Deposit allocation

Let:

```text
F   = deposit
V   = portfolio NAV before deposit
a_s = target capital share of strategy s
C_s = current assigned strategy capital
```

Desired capital:

```text
C*_s = a_s × (V + F)
```

Deficit:

```text
g_s = max(C*_s - C_s, 0)
```

When total deficit is positive:

```text
x_s = F × g_s / Σg_j
```

If every deficit is zero:

```text
x_s = F × a_s
```

Apply:

- enabled strategy filter;
- minimum and maximum strategy shares;
- strategy capacity;
- liquidity limits;
- minimum allocation;
- strategy priority;
- portfolio cash reserve.

### Withdrawal allocation

Let:

```text
W = absolute withdrawal amount
C*_s = a_s × (V - W)
h_s = max(C_s - C*_s, 0)
```

Allocate withdrawal from surpluses:

```text
x_s = W × h_s / Σh_j
```

Withdrawal order:

1. portfolio free cash;
2. strategy idle cash;
3. strategy capital surpluses;
4. position liquidation.

Supported liquidation policies:

```text
PROPORTIONAL
LOWEST_CONVICTION_FIRST
MOST_LIQUID_FIRST
LOWEST_COST_FIRST
PRIORITY_ORDER
```

### Invariants

- approved allocations sum to the approved flow within rounding tolerance;
- disabled strategies receive no deposits;
- maximum strategy shares are respected;
- flows are idempotent;
- positions are never edited directly;
- allocations create target changes and normal order intents.

---

## 9. Rebalancing

### Models

```text
RebalancePolicy
RebalanceRun
TargetPortfolioPosition
OrderIntentAttribution
```

Policy fields:

```text
instrument_drift_threshold
portfolio_drift_threshold
minimum_trade_notional
minimum_trade_quantity
cash_buffer_percent
fee_buffer
maximum_turnover
sell_before_buy
price_staleness_limit
```

Triggers:

```text
SCHEDULED
INSTRUMENT_DRIFT
PORTFOLIO_DRIFT
STRATEGY_TARGET_CHANGE
DEPOSIT
WITHDRAWAL
MANUAL
RECOVERY
```

### Calculation

For strategy `s` and instrument `i`:

```text
D*_i = Σ(A_s × w*_(s,i))
w*_i = D*_i / V
```

Current state:

```text
w_i = q_i × p_i / V
d_i = w*_i - w_i
```

Target and trade quantity:

```text
q*_i = w*_i × V / p_i
Δq_i = q*_i - q_i
Δq̂_i = L_i × round(Δq_i / L_i)
```

Where:

- `A_s` is allocated strategy capital;
- `w*_(s,i)` is strategy target weight;
- `V` is portfolio NAV;
- `q_i` is current quantity;
- `p_i` is executable reference price;
- `L_i` is lot size.

### Trigger rules

Rebalance when any is true:

```text
|d_i| > instrument threshold
Σ|d_i| > portfolio threshold
scheduled trigger
flow trigger
manual trigger
material strategy target change
```

### Suppress a trade when

- notional is below minimum;
- quantity is below minimum;
- price is stale;
- contract is not qualified;
- estimated cost exceeds benefit;
- turnover limit would be exceeded.

### Execution sequence

1. freeze a portfolio snapshot;
2. validate strategy targets;
3. net conflicting targets;
4. calculate target positions;
5. generate candidate sells and buys;
6. suppress immaterial trades;
7. apply turnover and risk limits;
8. reserve cash and fees;
9. submit risk-reducing sells first;
10. wait for configured fill threshold or timeout;
11. refresh cash and positions;
12. recalculate buys;
13. resize after material partial fills;
14. reconcile before completion.

### Cost-aware priority

Calculate:

```text
tracking-error benefit
spread cost
commission
estimated market impact
liquidity
strategy priority
risk-reduction benefit
```

Use deterministic ranking initially:

1. risk-reducing sells;
2. largest absolute drift;
3. highest strategy priority;
4. lowest estimated cost;
5. highest liquidity;
6. stable instrument-ID tie-breaker.

---

## 10. Single-Stock Allocation and Position Sizing

### Models

```text
PositionSizingPolicy
PositionSizingDecision
```

Store:

```text
target_quantity
risk_quantity
weight_quantity
liquidity_quantity
cash_quantity
broker_quantity
approved_quantity
entry_price
stop_price
risk_budget
binding_constraint
calculation_version
```

### Risk quantity

```text
Q_risk =
floor(
  (ρ_i × V) /
  (|P_i - S_i| × m_i)
)
```

Where:

- `ρ_i` is maximum portfolio loss fraction;
- `P_i` is entry price;
- `S_i` is stop or invalidation price;
- `m_i` is contract multiplier.

Reject invalid or too-small stop distances.

### Concentration quantity

```text
Q_weight =
floor(
  (w_max_i × V) /
  (P_i × m_i)
)
```

### Liquidity quantity

```text
Q_liquidity = floor(η_i × ADV_i)
```

Where:

- `η_i` is maximum participation rate;
- `ADV_i` is recent average daily volume.

### Cash quantity

```text
Q_cash =
floor(
  C_available /
  (P_i × m_i)
)
```

### Broker quantity

Calculate `Q_broker` from:

- lot size;
- fractional-share support;
- multiplier;
- minimum order;
- account restrictions;
- short availability.

### Final quantity

```text
Q_approved =
max(
  0,
  min(
    Q_target,
    Q_risk,
    Q_weight,
    Q_liquidity,
    Q_cash,
    Q_broker
  )
)
```

Store every limiting value and the binding constraint.

### Volatility-scaled allocation

For candidate `i`:

```text
u_i = z_i / σ_i
w_i = u_i / Σ|u_j|
```

Then:

1. cap instrument weights;
2. cap strategy exposure;
3. apply gross and net limits;
4. renormalize;
5. round to lot sizes;
6. run normal single-stock sizing.

---

## 11. Risk, OMS and Attribution

Allocation and rebalancing may create only:

```text
OrderIntent
```

Required path:

```text
AllocationDecision
 -> TargetPortfolioPosition
 -> OrderIntent
 -> PositionSizingDecision
 -> RiskCheckResult
 -> OMS Order
 -> IB_gateway
```

Risk may:

```text
APPROVE
RESIZE
HOLD
REJECT
```

For net orders created by several strategies, preserve attribution through:

```text
OrderIntentAttribution
```

Default fill attribution:

```text
PRO_RATA_TARGET_DELTA
```

Store strategy-level quantity, value, cost and P&L attribution.

---

## 12. Frontend Changes

Add pages:

```text
Streaming
Allocations
Rebalancing
```

Streaming page:

- Kafka connectivity;
- Flink job states;
- consumer lag;
- event and watermark lag;
- checkpoint status;
- dead-letter count;
- stale instrument count.

Allocations page:

- portfolio flows;
- strategy capital before/after;
- deficits and surpluses;
- allocation decisions;
- liquidation policy;
- unallocated cash;
- run status.

Rebalancing page:

- active policy;
- trigger;
- current and target weights;
- drift;
- trade deltas;
- suppressed trades;
- position-sizing limits;
- related orders and fills.

Do not expose Kafka credentials or Flink administrative controls.

---

## 13. APIs

Add:

```text
GET  /api/v1/streaming/health/
GET  /api/v1/streaming/topics/
GET  /api/v1/streaming/consumer-lag/
GET  /api/v1/streaming/dead-letter/

GET  /api/v1/allocations/policies/
POST /api/v1/allocations/flows/
GET  /api/v1/allocations/runs/
GET  /api/v1/allocations/runs/{id}/

GET  /api/v1/rebalancing/policies/
POST /api/v1/rebalancing/preview/
POST /api/v1/rebalancing/run/
GET  /api/v1/rebalancing/runs/
GET  /api/v1/rebalancing/runs/{id}/

POST /api/v1/position-sizing/preview/
GET  /api/v1/position-sizing/decisions/{id}/
```

Preview endpoints must never create orders.

Mutation endpoints require idempotency keys.

---

## 14. Scheduling

Use Celery Beat for:

```text
publish_outbox_events
run_scheduled_rebalances
refresh_strategy_capital_snapshots
run_periodic_reconciliation
check_stream_health
retry_failed_allocations
```

Use Flink for continuous stateful market processing.

Do not simulate streaming computations with frequent Celery polling.

---

## 15. Failure Handling

### Kafka unavailable

- commit business transactions to PostgreSQL;
- leave events in the outbox;
- mark streaming health degraded;
- block strategies that require stale stream data;
- do not lose order or ledger state.

### Flink unavailable

- stop new derived indicators;
- expire existing values by TTL;
- reject dependent orders;
- keep OMS and reconciliation operational.

### Interrupted rebalance

On restart:

1. load incomplete runs;
2. reconcile orders and fills;
3. refresh positions and cash;
4. avoid resubmitting completed quantities;
5. recalculate remaining trades;
6. resume or cancel according to policy.

### Duplicate or replayed events

- use `ConsumedEvent`;
- enforce database uniqueness;
- preserve stable event IDs;
- make Flink outputs deterministic;
- never create duplicate flows, bars, fills or orders.

---

## 16. Tests

### Kafka and outbox

- atomic outbox creation;
- retry and acknowledgement;
- duplicate consumer event;
- schema validation;
- decimal serialization;
- dead-letter routing.

### Flink

- normalization;
- deduplication;
- event-time bars;
- allowed lateness;
- corrected bar versions;
- indicators;
- stale-state transitions;
- checkpoint recovery.

### Flow allocation

- deficit-weighted deposit;
- zero-deficit deposit;
- disabled strategy;
- maximum strategy share;
- rounding remainder;
- cash-funded withdrawal;
- surplus-funded withdrawal;
- liquidation;
- insufficient liquidity;
- idempotent retry.

### Rebalancing

- strategy netting;
- drift calculation;
- lot rounding;
- minimum-notional suppression;
- sell-before-buy;
- fee/cash buffer;
- turnover cap;
- partial-fill recalculation;
- restart recovery;
- duplicate-order prevention.

### Position sizing

- each individual limit becomes binding;
- invalid stop;
- unavailable short inventory;
- volatility scaling;
- cap and renormalization;
- decimal precision.

### End-to-end

- market event -> Flink -> indicator -> strategy;
- strategy target -> rebalance -> order intent;
- deposit -> allocation -> rebalance;
- withdrawal -> liquidation plan;
- order intent -> sizing -> risk -> OMS;
- execution -> ledgers -> attribution;
- Kafka, Flink and Backend restart tests.

---

## 17. Rollout

### Phase 1: Event foundation

- Kafka;
- schemas;
- transactional outbox;
- idempotent consumers;
- health and metrics.

Keep the current synchronous execution path active.

### Phase 2: Streaming market data

- Flink normalization;
- bars;
- indicators;
- stale detection;
- persistence;
- output parity checks.

### Phase 3: Shadow calculations

- flow allocation;
- rebalancing;
- single-stock sizing;
- preview APIs;
- no order creation.

### Phase 4: Paper integration

- create order intents;
- run through risk and OMS;
- test deposits, withdrawals, partial fills and recovery.

### Phase 5: Event-driven integration

- publish strategy, order and execution events;
- validate replay;
- retain safe recovery fallbacks.

### Phase 6: Hardening

- load tests;
- failure injection;
- checkpoint and savepoint drills;
- reconciliation drills;
- operational runbooks.

---

## 18. Acceptance Criteria

The work is complete when:

1. Kafka and Flink start through local Compose.
2. No new public application is introduced.
3. PostgreSQL remains financial truth.
4. Business events use the outbox.
5. Consumers are idempotent.
6. Flink generates canonical market data, bars, indicators and quality state.
7. Stale data blocks dependent orders.
8. Deposits allocate by strategy deficits.
9. Withdrawals use cash, surpluses and configured liquidation.
10. Rebalancing nets strategy targets.
11. Drift, lot size, minimum trade, cost, turnover and buffers are applied.
12. Sells happen before buys by default.
13. Partial fills trigger recalculation.
14. Single-stock sizing records all limits.
15. Allocation and rebalancing create only order intents.
16. Risk, OMS, Gateway and reconciliation remain mandatory.
17. Replays and restarts create no duplicate orders.
18. Frontend shows streaming, allocations, rebalances and sizing.
19. All new execution remains paper or shadow mode by default.
20. Documentation, migrations and tests are complete.

---

## 19. Codex Rules

Codex must:

- modify the current implemented repository;
- preserve existing public APIs where practical;
- inspect and reuse existing models before creating duplicates;
- write migrations;
- implement working code, not placeholders;
- run Backend, Frontend, Flink and Compose tests;
- update `docs/IMPLEMENTATION_STATUS.md`;
- record assumptions in `docs/OPEN_QUESTIONS.md`;
- keep all new execution in paper/shadow mode;
- never let Kafka or Flink submit broker orders.
