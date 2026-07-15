# Multi-Goal Portfolio Builder Implementation Plan

## 1. Goal

Add a deterministic multi-goal portfolio-construction workflow before adding AI.

A user should be able to divide one `TradingPortfolio` into several virtual goal allocations. Each goal needs only:

- goal name
- percentage of the portfolio
- timeframe dropdown
- risk dropdown
- selected strategies and stocks

Example:

| Goal | Allocation | Timeframe | Risk |
|---|---:|---|---|
| Long-term growth | 50% | Grow, 3-7 years | Growth |
| High-risk / high-reward | 50% | Grow, 3-7 years | Aggressive |

Enabled goals must total 100% before preview or apply.

No target date, target amount, questionnaire, contribution schedule, or funding calculation is required.

---

## 2. Simple Architecture

Use one real broker-backed portfolio and multiple virtual construction slices:

```text
TradingPortfolio
    -> Construction Plan
        -> Goal A: 50%, GROW, Risk 4
        -> Goal B: 50%, GROW, Risk 5
```

Construct each goal separately, then combine the results:

```text
final stock weight
    = sum(goal allocation % x stock weight inside that goal)
```

If the same stock appears in several goals, merge its weights. Send only one combined target portfolio to the existing rebalancer.

Goals are planning slices, not separate broker portfolios. Do not add goal-level cash ledgers, position ledgers, fill accounting, or separate broker orders.

---

## 3. User Flow

Use one four-step Portfolio Builder:

1. **Allocate goals**
   - Add or remove goal rows.
   - Enter the percentage for each goal.
   - Select timeframe and risk from dropdowns.

2. **Select strategies and stocks**
   - Show eligible implemented strategies for each goal.
   - Let the user manually select strategy-stock pairs.

3. **Preview**
   - Show each goal allocation.
   - Show the combined portfolio.
   - Show the net rebalance trades.

4. **Apply**
   - Confirm once.
   - Apply one combined target through the existing pipeline.

---

## 4. Timeframe Dropdown

| Code | Label |
|---|---|
| `NOW` | Now, up to 30 days |
| `HURRY` | Hurry, 1-3 months |
| `FAST` | Fast, 3-12 months |
| `BUILD` | Build, 1-3 years |
| `GROW` | Grow, 3-7 years |
| `COMPOUND` | Compound, 7+ years |

Store the code as a fixed backend enum. Do not ask for a date.

---

## 5. Risk Dropdown

| Level | Code | Label |
|---:|---|---|
| 1 | `PRESERVATION` | Capital Preservation |
| 2 | `CONSERVATIVE` | Conservative |
| 3 | `BALANCED` | Balanced |
| 4 | `GROWTH` | Growth |
| 5 | `AGGRESSIVE` | Aggressive / High Risk-High Reward |

Allowed risk by timeframe:

| Timeframe | Maximum risk |
|---|---:|
| `NOW` | 1 |
| `HURRY` | 2 |
| `FAST` | 3 |
| `BUILD` | 4 |
| `GROW` | 5 |
| `COMPOUND` | 5 |

The frontend filters the risk dropdown. The backend validates it again.

---

## 6. Deterministic Construction Rules

Resolve these rules separately for every goal.

### Cash floor by timeframe

| Timeframe | Minimum cash |
|---|---:|
| `NOW` | 100% |
| `HURRY` | 70% |
| `FAST` | 40% |
| `BUILD` | 20% |
| `GROW` | 5% |
| `COMPOUND` | 2% |

### Cash floor by risk

| Risk | Minimum cash |
|---:|---:|
| 1 | 80% |
| 2 | 50% |
| 3 | 25% |
| 4 | 10% |
| 5 | 2% |

Use:

```text
goal cash weight = max(timeframe cash floor, risk cash floor)
```

### Maximum stock weight inside one goal

| Risk | Maximum single-stock weight |
|---:|---:|
| 1 | 5% |
| 2 | 10% |
| 3 | 15% |
| 4 | 20% |
| 5 | 25% |

### Optimizer method

- Risk 1-3: `MINIMUM_VARIANCE`
- Risk 4-5: `MAXIMUM_SHARPE`
- `NOW`: cash-only, no optimization

Use a 252-trading-day lookback and at least 60 aligned observations.

Keep version one long-only, stock-only, without leverage or short selling.

---

## 7. Backend Models

Create:

```text
Backend/apps/portfolio_construction/
```

### `PortfolioConstructionPlan`

One-to-one with `TradingPortfolio`.

Fields:

- `portfolio`
- `name`
- `status`: `DRAFT`, `ACTIVE`, `PAUSED`
- `version`
- timestamps

### `PortfolioGoalAllocation`

One row for each goal.

Fields:

- `plan`
- `name`
- `allocation_weight` stored from `0` to `1`
- `timeframe_bucket`
- `risk_level`
- `enabled`
- `display_order`
- timestamps

Rules:

- drafts may total less or more than 100% while being edited
- preview and apply require enabled goals to total exactly 100%
- use `Decimal`, not floating-point arithmetic
- allow at most ten enabled goals

### `StrategyConstructionProfile`

One-to-one with `StrategyDefinition`.

Fields:

- `strategy_definition`
- supported goal timeframe buckets
- minimum and maximum risk
- `construction_enabled`
- `user_selectable`
- summary and limitations

Do not reuse `StrategyDefinition.supported_timeframes`; that field represents execution or market-data intervals.

### `GoalStrategySelection`

Stores the selected strategy-stock pair for one goal.

Fields:

- `goal_allocation`
- `strategy_definition`
- `instrument`
- `execution_timeframe`
- `parameter_overrides`
- `enabled`
- nullable `created_strategy_instance`
- timestamps

Validate that the strategy is implemented and eligible, the instrument is an active tradable stock, and parameters match the existing schema.

### `PortfolioConstructionRun`

Immutable async preview/application record.

Store:

- plan reference
- idempotency and request hash
- run and application statuses
- plan, goal, selection, and policy snapshots
- per-goal results
- final combined target weights
- metrics and warnings
- retry state
- optional applied rebalance
- timestamps

Per-goal results may be stored in structured JSON or a small `GoalConstructionTarget` table. Use the table only if it makes API queries and audit output cleaner. Do not create goal position or ledger tables.

---

## 8. Strategy Eligibility

A strategy is eligible only when it is:

```text
implemented
AND enabled
AND construction-enabled
AND compatible with the goal timeframe
AND compatible with the goal risk
AND supported for stocks
AND supported by available data
AND does not require leverage or short selling
```

Return rejected strategies with a short reason. Do not silently hide them.

---

## 9. Reuse the Existing Optimizer

The current system has one `PortfolioUniverse` and one `PortfolioOptimizationPolicy` per portfolio. Do not overwrite them repeatedly for different goals.

Refactor the existing optimization service into:

1. **Reusable optimization core**
   - accepts an explicit stock universe and resolved policy values
   - loads aligned price history
   - calculates returns and covariance
   - calls the existing `solve_markowitz`
   - returns weights and metrics

2. **Existing optimization workflow**
   - keeps using its current universe, policy, run models, APIs, and frontend

3. **Portfolio Builder workflow**
   - calls the same reusable core once for every goal

Do not create another Markowitz implementation.

### Simple edge cases

- `NOW`: 100% cash
- no stocks selected: preview as cash with a warning; block apply unless intentionally cash-only
- one stock selected: allocate only up to the goal's single-stock limit and keep the rest as cash
- two or more stocks: run Markowitz

Do not enforce goal-level turnover because actual broker positions are consolidated. Enforce turnover only on the final combined rebalance.

---

## 10. Combining Goals

For each goal:

```text
goal NAV = portfolio NAV x goal allocation weight
```

After each goal produces local weights:

```text
portfolio stock weight
    = sum(goal allocation weight x local goal stock weight)

portfolio cash weight
    = sum(goal allocation weight x local goal cash weight)
```

Then:

- merge duplicate stocks
- confirm stock plus cash equals 100%
- calculate target values from total portfolio NAV
- calculate combined expected return, volatility, and Sharpe ratio
- preserve per-goal warnings and contributions for display

---

## 11. Rebalancer Integration

Extend the existing rebalancer instead of creating another one.

Add:

- `GOAL_CONSTRUCTION` as a `RebalanceRun.target_source`
- nullable construction-run reference on `RebalanceRun`
- support for explicit target weights from a completed construction run

The existing rebalancer remains responsible for:

- current positions and prices
- drift
- cash and fee buffers
- lot-size rounding
- minimum trades
- turnover
- sell-before-buy sequencing
- position sizing
- risk checks
- OMS and paper execution

Create one net rebalance for the whole portfolio. Never create separate broker orders for each goal.

---

## 12. Strategy Instances

Applying a construction should not automatically start strategies.

After confirmation:

- create or reuse matching `StrategyInstance` records
- keep them in `SHADOW` mode
- keep them disabled
- link selections to the instances
- let the user review and enable them manually from the Strategies page

Reuse one instance when identical strategy, stock, timeframe, and parameters appear in several goals.

---

## 13. API Plan

Use existing response envelopes, validation helpers, audits, idempotency keys, Celery tasks, and polling.

```text
GET/POST  /api/v1/portfolio-construction/plans/
PATCH     /api/v1/portfolio-construction/plans/{plan_id}/

POST      /api/v1/portfolio-construction/plans/{plan_id}/goals/
PATCH     /api/v1/portfolio-construction/goals/{goal_id}/
DELETE    /api/v1/portfolio-construction/goals/{goal_id}/

GET       /api/v1/portfolio-construction/goals/{goal_id}/eligible-strategies/
GET/POST  /api/v1/portfolio-construction/goals/{goal_id}/selections/
DELETE    /api/v1/portfolio-construction/selections/{selection_id}/

POST      /api/v1/portfolio-construction/preview/
GET       /api/v1/portfolio-construction/runs/
GET       /api/v1/portfolio-construction/runs/{run_id}/
POST      /api/v1/portfolio-construction/runs/{run_id}/apply/
```

Plan responses should include:

- current allocated percentage
- whether the plan is ready to preview
- validation errors
- resolved rules for each goal

Preview and apply return `202 Accepted` and are polled until completion.

---

## 14. Frontend Plan

Add:

```text
/portfolio-builder
```

Add **Portfolio Builder** to the main navigation.

### Step 1: Allocate goals

Show editable rows with:

- name
- allocation percentage
- timeframe dropdown
- filtered risk dropdown
- remove action

Show a live total such as:

```text
Allocated: 85% of 100%
```

Disable preview until the plan is valid.

### Step 2: Select strategies and stocks

Show one tab or collapsible card per goal. Let the user add and remove eligible strategy-stock selections.

### Step 3: Preview

Show:

- each goal's percentage, timeframe, risk, cash, stocks, and local weights
- each stock's contribution to the full portfolio
- the final combined cash and stock allocation
- current versus proposed weights
- combined metrics
- one net list of planned trades

Clearly identify stocks shared by several goals.

### Step 4: Apply

Apply once through the existing SHADOW or PAPER workflow and show links to the construction run, rebalance, and disabled strategy instances.

Rename the current Portfolio-page **Portfolio construction** panel to **Advanced target optimizer**. Keep it available for operators.

---

## 15. Implementation Phases

### Phase 1: Models and rules

- add the new app and migrations
- add timeframe, risk, allocation, and policy validation
- add model and service tests

### Phase 2: Plan and goal APIs

- implement plan and goal CRUD
- expose percentage totals and validation state
- add audit and API tests

### Phase 3: Strategy suitability

- add construction profiles to implemented strategies
- implement eligibility and selections
- add tests

### Phase 4: Optimizer refactor

- extract the reusable optimization core
- keep existing optimization APIs unchanged
- add regression tests

### Phase 5: Multi-goal preview

- add async construction runs
- construct every goal
- combine weights and metrics
- add idempotency, retry, audit, and task tests

### Phase 6: Apply

- add explicit construction targets to the rebalancer
- create one `GOAL_CONSTRUCTION` rebalance
- create or reuse disabled SHADOW strategy instances
- add end-to-end tests

### Phase 7: Frontend and documentation

- implement the four-step Portfolio Builder
- add frontend tests and polling states
- update README and async-operation documentation
- add `docs/PORTFOLIO_BUILDER.md`

---

## 16. Essential Tests

Test at minimum:

- all six timeframe options and five risk options
- invalid timeframe-risk combinations
- draft plans with incomplete percentages
- preview/apply rejection unless enabled goals total 100%
- a 50% plus 50% plan
- cash-only, one-stock, and multi-stock goals
- duplicate stocks across goals
- correct weighted aggregation
- combined weights equal 100%
- existing optimizer records are not overwritten
- async preview and retry behavior
- one-time idempotent apply
- one net `GOAL_CONSTRUCTION` rebalance
- disabled SHADOW strategy-instance creation and reuse
- no regressions in optimization, rebalancing, sizing, risk, OMS, execution, and frontend pages

Run:

```text
cd Backend && pytest
cd ../Frontend && npm test && npm run build
cd ../IB_gateway && pytest
cd .. && python -m pytest streaming/flink/tests
docker compose config --quiet
```

---

## 17. Acceptance Criteria

The work is complete when:

1. A portfolio supports several goal rows.
2. Every goal has a percentage, timeframe, and risk dropdown.
3. Enabled goal percentages must total 100% before preview or apply.
4. Strategies and stocks are selected separately for each goal.
5. Every goal produces a simple explainable target allocation.
6. Duplicate stocks are merged into one final weight.
7. One combined target enters the existing rebalancer.
8. Existing Markowitz logic is reused, not duplicated.
9. Existing optimization APIs continue working.
10. One SHADOW or PAPER rebalance is created.
11. Strategy instances remain disabled until manually enabled.
12. No AI, questionnaire, target-date system, funding engine, leverage, short selling, backtesting, or goal-level financial ledger is added.

---

## 18. Future AI Boundary

Later, AI may propose:

- goal names
- allocation percentages
- timeframe and risk selections
- eligible strategies and stocks
- explanations of the preview

AI must use the same draft APIs as the manual frontend.

AI must not bypass validation, apply a construction, enable strategies, or create orders.
