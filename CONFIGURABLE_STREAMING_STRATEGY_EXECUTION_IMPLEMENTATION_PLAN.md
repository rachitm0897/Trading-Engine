# Configurable Streaming Strategy Execution
## Incremental Implementation Plan for the Existing Trading Engine

## 1. Objective

Extend the current working IBKR trading engine with a reusable streaming strategy framework.

TSLA with RSI is only the first example and validation case. The implementation must not hard-code:

- `TSLA`;
- RSI;
- a 5-minute timeframe;
- entry threshold 30;
- exit threshold 65;
- long-only execution;
- one strategy per instrument.

The completed system must allow an operator to:

1. select or change the ticker or instrument;
2. select a supported strategy type;
3. configure strategy parameters;
4. select a timeframe;
5. run multiple strategy instances;
6. attach multiple strategies to the same ticker;
7. use the same strategy on multiple tickers;
8. add new strategy plugins without changing the execution pipeline;
9. enable, pause, version and retire strategy instances;
10. preserve one common strategy-to-order workflow.

Required shared workflow:

```text
Market stream
  -> Flink bars and indicators
  -> Strategy plugin evaluation
  -> StrategyTarget
  -> Portfolio aggregation
  -> Rebalancing
  -> OrderIntent
  -> Position sizing
  -> Risk
  -> OMS
  -> IB_gateway
  -> IBKR
  -> Executions
  -> Ledgers
  -> Reconciliation
```

No strategy plugin may place broker orders directly.

---

## 2. Example Validation Case

Use the following only as the initial end-to-end example:

```text
Ticker: TSLA
Strategy: RSI mean reversion
Timeframe: 5-minute bars
RSI window: 14
Entry: cross above 30 after being below 30
Exit: cross above 65
Direction: long only
Target weight: 5%
```

This example is used to verify the complete implementation.

After implementation, the same system must support configurations such as:

```text
AAPL + RSI mean reversion
MSFT + SMA crossover
NVDA + Donchian breakout
SPY + volatility-target momentum
TSLA + multiple simultaneous strategies
```

Changing the ticker or strategy must require configuration or database changes only, not a new execution service or separate code path.

---

## 3. Generic Domain Model

Separate the reusable strategy definition from an active strategy instance.

### 3.1 StrategyDefinition

Represents a strategy plugin type.

Required fields:

```text
key
name
description
plugin_path
input_requirements
parameter_schema
supported_asset_types
supported_directions
supported_timeframes
version
enabled
```

Example keys:

```text
RSI_MEAN_REVERSION
SMA_CROSSOVER
DONCHIAN_BREAKOUT
VOLATILITY_TARGET_MOMENTUM
FIXED_WEIGHT_REBALANCE
```

### 3.2 StrategyInstance

Represents one configured strategy running on one instrument or universe.

Required fields:

```text
name
definition
portfolio
instrument
universe_optional
timeframe
parameters
target_configuration
risk_policy
order_policy
execution_mode
state
enabled
version
effective_from
effective_to
```

Examples:

```text
TSLA_RSI_5M
AAPL_RSI_15M
MSFT_SMA_1H
SPY_MOMENTUM_1D
```

### 3.3 StrategyVersion

Every material configuration change must create a new immutable version.

Store:

```text
strategy_instance
version
configuration_snapshot
parameter_hash
created_at
activated_at
retired_at
```

Every strategy run, signal, target and order intent must reference the exact version.

---

## 4. Strategy Plugin Interface

Create a common plugin interface.

Each strategy plugin must declare:

```text
strategy key
required indicators
required bar fields
default parameters
parameter validation rules
supported directions
warm-up requirement
evaluate method
target-generation method
```

Conceptual interface:

```text
validate_configuration()
required_stream_inputs()
warmup_bars()
evaluate(context)
build_target(signal, context)
```

The evaluation context must contain:

```text
strategy_instance
strategy_version
instrument
final bars
indicator values
previous strategy state
current attributed position
active orders
portfolio state
market session
event metadata
```

The plugin output must be one of:

```text
ENTER_LONG
EXIT_LONG
ENTER_SHORT
EXIT_SHORT
SET_TARGET
HOLD
NO_ACTION
```

The plugin output must include a desired target, not a broker order.

---

## 5. Instrument Configuration

The instrument must be selected through the canonical `Instrument` and `BrokerContract` models.

Do not identify instruments only through ticker strings.

Required data:

```text
instrument_id
symbol
security_type
currency
exchange
primary_exchange
IBKR conId
multiplier
minimum_tick
lot_size
fractional_support
trading_calendar
active
```

The UI may accept a ticker such as `TSLA`, but the Backend must resolve it to a canonical instrument and qualified IBKR contract before activating the strategy.

A strategy should be portable from TSLA to another instrument by changing:

```text
instrument
timeframe
parameters
risk policy
order policy
```

---

## 6. Supported Initial Strategies

Implement the framework so it can support at least these existing strategy types:

### RSI Mean Reversion

Required indicators:

```text
RSI
```

Configurable parameters:

```text
window
entry_threshold
exit_threshold
entry_rule
exit_rule
direction
target_weight
```

### SMA Crossover

Required indicators:

```text
fast SMA
slow SMA
```

Configurable parameters:

```text
fast_window
slow_window
entry_rule
exit_rule
direction
target_weight
```

### Donchian Breakout

Required indicators:

```text
upper channel
lower channel
```

Configurable parameters:

```text
entry_window
exit_window
direction
target_weight
```

### Volatility-Target Momentum

Required indicators:

```text
momentum
realized volatility
```

Configurable parameters:

```text
momentum_window
volatility_window
target_volatility
maximum_weight
direction
```

### Fixed-Weight Rebalance

Required inputs:

```text
configured target weights
current portfolio state
```

The TSLA RSI strategy should be the first fully activated example, but the architecture must remain generic.

---

## 7. Dynamic Stream Requirements

The system must derive market subscriptions and Flink computations from active strategy instances.

Example:

```text
TSLA_RSI_5M
```

requires:

```text
TSLA market data
5-minute bars
RSI(14)
```

Example:

```text
MSFT_SMA_1H
```

requires:

```text
MSFT market data
1-hour bars
SMA(20)
SMA(50)
```

Add a strategy-input registry that determines:

```text
active instruments
required timeframes
required indicators
indicator parameters
warm-up requirements
```

When a strategy is enabled:

1. validate the instrument;
2. qualify the IBKR contract;
3. register the stream requirements;
4. ensure the market subscription exists;
5. ensure the required Flink computation exists;
6. warm up the indicator state;
7. mark the strategy ready only after sufficient data exists.

When disabled:

1. stop new evaluations;
2. preserve audit history;
3. remove stream requirements only if no other strategy needs them;
4. do not automatically close positions unless explicitly configured.

---

## 8. Generic Market Data Flow

Publish raw market events to:

```text
market.raw.v1
```

Partition by:

```text
instrument_id
```

Flink must generate canonical bars for every active instrument/timeframe pair.

Output:

```text
market.bars.v1
```

Required bar fields:

```text
instrument_id
timeframe
bar_open_time
bar_close_time
open
high
low
close
volume
source_event_count
bar_version
is_final
event_id
```

Rules:

- event-time processing;
- watermarks;
- allowed lateness;
- stable bar IDs;
- corrected bar versions;
- strategy evaluation only on final bars;
- idempotent persistence.

No Flink job should contain a hard-coded TSLA filter.

---

## 9. Generic Indicator Computation

Flink must calculate indicators according to the active strategy-input registry.

Output:

```text
market.indicators.v1
```

Required fields:

```text
instrument_id
timeframe
bar_time
indicator_name
indicator_version
parameters
parameters_hash
value
previous_value
source_bar_id
source_bar_version
is_final
event_id
```

Indicator identity is:

```text
instrument
+ timeframe
+ indicator name
+ parameter hash
+ bar time
+ source bar version
```

The same indicator stream may be shared by several strategies.

Example:

```text
TSLA RSI(14) 5m
```

may feed multiple strategy instances with different thresholds.

Do not recompute identical indicators separately for every strategy.

---

## 10. Generic Strategy State Machine

Each `StrategyInstance` has its own state.

Base states:

```text
FLAT
ENTRY_PENDING
PARTIALLY_LONG
LONG
EXIT_PENDING
PARTIALLY_SHORT
SHORT
PAUSED
BLOCKED
WARMING_UP
ERROR
```

A plugin may use only the relevant subset.

State must be scoped by:

```text
strategy_instance_id
instrument_id
portfolio_id
```

Multiple strategies on the same ticker must maintain separate strategy states and attribution.

Example:

```text
TSLA_RSI_5M = LONG
TSLA_SMA_1H = FLAT
```

The portfolio may still hold one net TSLA position.

---

## 11. Generic Strategy Evaluation

The strategy evaluator consumes final bars and indicator events.

For every relevant event:

1. find active strategy instances requiring the event;
2. validate instrument and timeframe;
3. validate warm-up completion;
4. validate configuration version;
5. load previous required values;
6. load strategy state;
7. load strategy-attributed position;
8. load active strategy orders;
9. validate session, cooldown and freshness;
10. invoke the strategy plugin;
11. create a reproducible `StrategyRun`;
12. create a `StrategySignal`;
13. create a `StrategyTarget` only when the desired target changes.

A strategy plugin must not know how to:

- allocate portfolio capital;
- choose final order quantity;
- call the Gateway;
- allocate an IBKR order ID;
- process a broker fill.

Those remain shared platform responsibilities.

---

## 12. Idempotency

Use a generic strategy-evaluation key:

```text
strategy_instance_id
+ strategy_version
+ instrument_id
+ timeframe
+ triggering_event_id
+ source_data_version
```

Use deterministic keys for:

```text
StrategyRun
StrategySignal
StrategyTarget
RebalanceRun
OrderIntent
OMS Order
Gateway command
```

Replays must not duplicate any of these.

Changing the ticker or strategy configuration creates a different strategy instance/version and therefore a separate idempotency namespace.

---

## 13. Strategy Target Contract

All strategy plugins must produce a common target format.

Required fields:

```text
strategy_run
strategy_instance
strategy_version
portfolio
instrument
target_type
target_weight
target_value
target_quantity_optional
direction
signal_type
signal_time
source_event_id
reason
confidence_optional
status
```

Target types:

```text
WEIGHT
VALUE
QUANTITY
FLAT
```

Preferred default:

```text
WEIGHT
```

Examples:

```text
TSLA target weight = 5%
AAPL target weight = 3%
MSFT target weight = 0%
```

This common contract allows every new strategy to reuse the same downstream services.

---

## 14. Multiple Strategies and Target Aggregation

Several strategies may target the same instrument.

Example:

```text
TSLA RSI strategy target:       +5% portfolio weight
TSLA momentum strategy target:  -2% portfolio weight
TSLA fixed allocation target:   +1% portfolio weight
```

The allocation layer must combine strategy capital and target weights into a portfolio-level target.

Preserve:

```text
strategy contribution
strategy capital
strategy target delta
strategy priority
strategy risk budget
```

Create one net portfolio trade while retaining `OrderIntentAttribution`.

Default attribution policy:

```text
PRO_RATA_TARGET_DELTA
```

Do not place separate opposing IBKR orders for strategies that can be netted internally.

---

## 15. Rebalancing

Use the existing generic rebalancing service.

For every instrument:

```text
portfolio target exposure
current portfolio exposure
target quantity
current quantity
trade delta
drift
```

Apply:

- strategy target aggregation;
- lot-size rounding;
- minimum quantity;
- minimum notional;
- cash and fee buffers;
- portfolio concentration;
- turnover;
- stale-price validation;
- cost-aware priority;
- sell-before-buy where applicable.

Changing the ticker must not require rebalancing code changes.

---

## 16. Generic Single-Stock Sizing

Every instrument target must pass through the same position-sizing service.

Calculate:

```text
Q_target
Q_risk
Q_weight
Q_liquidity
Q_cash
Q_broker
```

Approved quantity:

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

Sizing inputs must come from:

```text
strategy risk policy
instrument metadata
portfolio NAV
reference price
stop/invalidation rule
ADV or liquidity estimate
cash and buying power
IBKR contract rules
```

Do not embed TSLA-specific volatility, stop size or lot rules.

---

## 17. Order Policy

Create a reusable `OrderPolicy`.

Fields:

```text
order_type
time_in_force
limit_offset_bps
price_collar_bps
allow_market_order
replace_after_seconds
maximum_replacements
cancel_at_session_end
outside_regular_hours
```

Different strategy instances may use different order policies.

Example:

```text
TSLA RSI -> marketable limit
SPY daily rebalance -> limit
AAPL breakout -> stop-limit
```

The strategy plugin selects a target, not a raw broker order.

OMS constructs the order according to the attached policy.

---

## 18. Operating Modes

Each strategy instance supports:

```text
OBSERVE
SHADOW
PAPER
LIVE
```

### Observe

- market and indicator computation;
- no strategy targets.

### Shadow

- strategy runs;
- signals;
- targets;
- rebalancing;
- sizing;
- risk;
- no OMS order submission.

### Paper

- complete execution through IBKR paper account.

### Live

- controlled by existing platform-wide live-trading safeguards;
- unavailable by default for new strategy instances.

Default for every new strategy instance:

```text
SHADOW
```

---

## 19. Strategy Management APIs

Add generic APIs:

```text
GET  /api/v1/strategy-definitions/
GET  /api/v1/strategy-definitions/{key}/

GET  /api/v1/strategy-instances/
POST /api/v1/strategy-instances/
GET  /api/v1/strategy-instances/{id}/
PATCH /api/v1/strategy-instances/{id}/

POST /api/v1/strategy-instances/{id}/enable/
POST /api/v1/strategy-instances/{id}/pause/
POST /api/v1/strategy-instances/{id}/evaluate/
POST /api/v1/strategy-instances/{id}/flatten/

GET  /api/v1/strategy-instances/{id}/state/
GET  /api/v1/strategy-instances/{id}/signals/
GET  /api/v1/strategy-instances/{id}/runs/
GET  /api/v1/strategy-instances/{id}/targets/
GET  /api/v1/strategy-instances/{id}/execution-timeline/
```

Creating a strategy instance should accept:

```text
definition key
ticker or instrument ID
portfolio
timeframe
parameters
target configuration
risk policy
order policy
execution mode
```

The Backend must validate all parameters against the strategy definition schema.

---

## 20. Frontend Strategy Builder

Add a generic strategy creation and configuration flow.

### Step 1: Select instrument

Allow:

- ticker search;
- exchange selection when ambiguous;
- contract verification;
- display of canonical instrument and IBKR conId.

### Step 2: Select strategy

Display available `StrategyDefinition` plugins.

### Step 3: Configure parameters

Render fields from the plugin's parameter schema.

Examples:

```text
RSI window
entry threshold
exit threshold
SMA fast window
SMA slow window
Donchian entry window
target volatility
```

### Step 4: Configure execution

Select:

```text
timeframe
target weight
risk policy
order policy
execution mode
regular-hours rule
cooldown
```

### Step 5: Validate and activate

Show:

```text
required market subscriptions
required indicators
warm-up bars
estimated readiness
risk limits
paper/shadow status
```

New strategy instances must start in shadow mode unless explicitly moved to paper mode.

---

## 21. Frontend Monitoring

For each strategy instance display:

- ticker and canonical instrument;
- strategy type;
- strategy version;
- timeframe;
- parameters;
- required indicators;
- warm-up progress;
- state;
- last final bar;
- latest indicator values;
- latest signal;
- current target;
- attributed position;
- active order;
- last fill;
- cooldown;
- block reason;
- execution mode.

Provide filters by:

```text
portfolio
ticker
strategy type
state
execution mode
```

---

## 22. Adding New Strategies

A new strategy should require:

1. one plugin implementation;
2. one parameter schema;
3. required-input declarations;
4. unit tests;
5. registration in `StrategyDefinition`.

It should not require changes to:

- rebalancing;
- risk;
- OMS;
- Gateway;
- execution ledger;
- reconciliation;
- common frontend execution timeline.

Add developer documentation:

```text
docs/ADDING_A_STRATEGY_PLUGIN.md
```

Include a template strategy plugin and test fixture.

---

## 23. Initial TSLA RSI Validation

Use TSLA RSI as the first integration test.

Validate:

```text
TSLA data
-> 5-minute final bar
-> RSI(14)
-> crossing signal
-> target weight
-> rebalance
-> sizing
-> risk
-> OMS
-> IBKR paper order
-> fills
-> ledgers
-> reconciliation
```

After this works, validate portability with at least:

```text
AAPL using the same RSI plugin
MSFT using the SMA plugin
```

These portability tests must prove there are no hard-coded TSLA or RSI assumptions.

---

## 24. Tests

### Generic framework tests

- strategy-definition registration;
- parameter-schema validation;
- dynamic ticker selection;
- duplicate strategy instance rules;
- version creation;
- input requirement registration;
- shared indicator reuse;
- strategy warm-up;
- generic target contract;
- plugin exception isolation.

### Ticker portability

Run the RSI plugin against:

```text
TSLA
AAPL
```

Confirm identical logic with different instrument metadata.

### Strategy portability

Run different plugins against the same instrument:

```text
TSLA RSI
TSLA SMA
```

Confirm separate state and shared execution infrastructure.

### Multi-strategy netting

Test opposing targets for the same instrument.

Confirm:

- one net portfolio trade;
- preserved strategy attribution;
- no duplicate opposing broker orders.

### Existing execution tests

Retain:

- sizing;
- risk;
- partial fills;
- order rejection;
- cancellation;
- restart;
- reconciliation;
- Kafka replay;
- corrected bars.

---

## 25. Rollout

### Phase 1: Generic strategy framework

- definitions;
- instances;
- plugin interface;
- configuration validation;
- versioning;
- dynamic input registry.

### Phase 2: TSLA RSI example

- complete shadow flow;
- paper execution;
- recovery tests.

### Phase 3: Ticker portability

- run RSI on AAPL or another configured stock;
- confirm no TSLA-specific code.

### Phase 4: Strategy portability

- enable SMA crossover on a configured instrument;
- confirm no RSI-specific execution code.

### Phase 5: Multi-strategy operation

- multiple strategy instances;
- shared indicators;
- target netting;
- attribution;
- portfolio-level risk.

### Phase 6: Plugin documentation

- plugin template;
- developer guide;
- registration workflow;
- test requirements.

---

## 26. Acceptance Criteria

The implementation is complete when:

1. TSLA is only an example configuration.
2. The ticker can be changed through the API and Frontend.
3. Instruments are resolved to canonical records and IBKR contracts.
4. RSI is only one strategy plugin.
5. New strategy plugins use a documented interface.
6. Strategy parameters are validated through schemas.
7. Multiple strategy instances may run simultaneously.
8. One strategy may run on multiple tickers.
9. Multiple strategies may run on one ticker.
10. Identical indicator computations are shared.
11. Each strategy instance has separate state and versioning.
12. All strategies produce the same target contract.
13. Targets are aggregated and netted before orders.
14. Strategy attribution is preserved.
15. Rebalancing, sizing, risk, OMS and Gateway remain generic.
16. No plugin places broker orders directly.
17. Every new strategy starts in shadow mode.
18. TSLA RSI works end to end in paper mode.
19. The same RSI plugin works on a second ticker without code changes.
20. A second strategy plugin works through the same execution path.
21. Replays and restarts do not duplicate orders.
22. All tests and documentation are complete.

---

## 27. Codex Working Rules

Codex must:

- modify the current working trading-engine repository;
- treat TSLA RSI as an example, not a hard-coded product;
- inspect and reuse existing strategy, stream, risk, OMS, Gateway and reconciliation code;
- create a generic plugin-based strategy framework;
- avoid duplicate execution paths;
- write migrations;
- preserve backward compatibility where practical;
- implement working code rather than placeholders;
- add ticker-portability and strategy-portability tests;
- keep new strategy instances in shadow mode by default;
- use IBKR paper trading for executable tests;
- update `docs/IMPLEMENTATION_STATUS.md`;
- record assumptions in `docs/OPEN_QUESTIONS.md`;
- never allow strategy plugins or Flink jobs to submit broker orders directly.
