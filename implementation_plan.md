# Multi-Goal Portfolio Builder
## Stock and Strategy Integration Implementation Plan

**Repository:** `rachitm0897/Trading-Engine`

## 1. Objective

Implement a complete stock and strategy workflow inside the current multi-goal Portfolio Builder while preserving the existing safety model:

- one broker-backed `TradingPortfolio`;
- virtual goal allocations only;
- one final merged portfolio target;
- one net rebalance;
- long-only, unlevered construction;
- SHADOW or PAPER execution only;
- strategy instances created disabled in SHADOW mode.

The implementation must let an operator:

1. search and qualify a new stock from the Portfolio Builder;
2. add the stock once to a goal universe;
3. assign one or more strategies to that stock;
4. edit strategy parameters using the plugin schema;
5. divide the stock allocation explicitly among assigned strategies;
6. preview both stock weights and strategy-controlled weights;
7. apply one combined rebalance;
8. create or update correctly sized disabled SHADOW strategy instances.

## 2. Current Behaviour and Problems

### 2.1 Stock and strategy are mixed into one model

`GoalStrategySelection` currently represents both stock inclusion and strategy assignment. The optimizer deduplicates selections by `instrument_id`, so the strategy choice does not affect stock construction.

### 2.2 Strategy choice does not affect portfolio weights

For every goal, the construction service extracts unique stocks and applies the goal rules and Markowitz optimizer. Strategy type, parameters, and signals are ignored during construction.

This behaviour should remain explicit: the optimizer determines stock weights, while strategy assignments determine who manages each allocated stock weight.

### 2.3 Builder-created strategy instances are incorrectly sized

The apply service creates strategy instances with an empty `target_configuration`.

Several built-in plugins obtain their exposure from `target_configuration["target_weight"]`. An empty target configuration therefore produces a zero target and can cause a newly enabled strategy to flatten a position created by the Portfolio Builder.

### 2.4 Multiple strategies on one stock have no ownership rule

The current design allows several strategy-stock selections but does not define how the stock target is divided among them.

### 2.5 New stocks cannot be registered inside Portfolio Builder

The repository already supports IBKR contract search and exact contract qualification, but the Portfolio Builder only lists instruments already stored in the database.

### 2.6 Strategy parameters cannot be edited in Portfolio Builder

The backend returns plugin parameter schemas, but the frontend submits default parameters only.

## 3. Target Architecture

Separate stock construction from strategy ownership.

### 3.1 New model: `GoalInstrumentSelection`

| Field | Type | Purpose |
|---|---|---|
| `goal_allocation` | ForeignKey | Parent goal |
| `instrument` | ForeignKey | Stock included in the goal universe |
| `enabled` | Boolean | Include or exclude without deleting |
| `minimum_weight` | Decimal, nullable | Optional local lower bound |
| `maximum_weight` | Decimal, nullable | Optional local upper bound |
| `display_order` | Positive integer | Stable frontend ordering |
| timestamps | DateTime | Auditability |

Constraints:

- unique `(goal_allocation, instrument)`;
- instrument must be active, tradable, and `STK`;
- minimum and maximum weights must be between 0 and 1;
- minimum weight must not exceed maximum weight.

### 3.2 New model: `GoalStrategyAssignment`

| Field | Type | Purpose |
|---|---|---|
| `goal_instrument_selection` | ForeignKey | Stock being managed |
| `strategy_definition` | ForeignKey | Selected plugin definition |
| `execution_timeframe` | CharField | Market-data and evaluation interval |
| `parameter_overrides` | JSONField | Validated plugin parameters |
| `strategy_share` | Decimal | Share of this goal-stock weight |
| `risk_policy` | ForeignKey, nullable | Optional strategy risk policy |
| `order_policy` | ForeignKey, nullable | Optional execution policy |
| `create_instance` | Boolean | Whether apply creates a strategy instance |
| `enabled` | Boolean | Active assignment |
| `created_strategy_instance` | ForeignKey, nullable | Applied instance |
| timestamps | DateTime | Auditability |

Constraints:

- unique assignment identity for stock, strategy, timeframe, and parameter hash;
- `strategy_share` must be between 0 and 1;
- for every enabled goal-stock selection, enabled assignments with `create_instance=true` must total exactly 1 before apply;
- one enabled assignment may default automatically to a share of 1.

### 3.3 Weight calculations

For goal `g` and stock `i`:

`P(g,i) = A(g) × L(g,i)`

Where:

- `A(g)` is the goal allocation;
- `L(g,i)` is the optimizer's local stock weight;
- `P(g,i)` is the stock's contribution to the complete portfolio.

For strategy `k` assigned to that goal-stock pair:

`T(g,i,k) = P(g,i) × beta(g,i,k)`

Where `beta` is `strategy_share`, and enabled shares for each goal-stock pair total 1.

For a reusable strategy identity across several goals:

`T(i,k) = sum over goals of T(g,i,k)`

`T(i,k)` becomes the strategy instance's `target_configuration.target_weight`.

## 4. Required Behaviour

### 4.1 Stock construction

- The optimizer must use `GoalInstrumentSelection`, not strategy assignments.
- Selecting more strategies must not increase a stock's optimizer weight.
- Duplicate stocks across goals must continue to merge into one final stock target.
- Existing cash floors, risk caps, optimizer methods, history requirements, and long-only rules must remain unchanged.
- A non-`NOW` goal with no enabled stocks may preview as cash-only but must block apply.

### 4.2 Strategy assignment

- Every selected stock must have at least one enabled assignment before apply.
- The assignment must pass the existing `StrategyConstructionProfile` eligibility rules.
- The plugin configuration must pass `validate_configuration`.
- Portfolio Builder assignments must remain `LONG`.
- Strategy shares must total exactly 100% per goal-stock pair.
- Assignment validation must run again at snapshot time.

### 4.3 Strategy instance creation and reuse

On apply:

1. aggregate target weights by strategy definition, instrument, execution timeframe, validated parameter hash, risk policy, and order policy;
2. reuse only a disabled SHADOW instance with the same identity;
3. if the reusable instance has an outdated target configuration, call the existing update workflow so a new immutable strategy version is created;
4. otherwise create a new instance;
5. set:

```json
{
  "target_weight": "<aggregated strategy weight>",
  "capital_share": "<aggregated strategy weight>",
  "priority": 100,
  "construction_run_id": "<run id>"
}
```

6. leave every created or updated instance disabled and in SHADOW mode;
7. never modify an enabled, PAPER, OBSERVE, or otherwise incompatible instance;
8. link every assignment to its created or reused instance.

The resulting target weight must never silently default to zero.

### 4.4 Rebalancing

The existing final combined stock target remains the only input to the rebalancer.

Do not create goal-level broker orders, strategy-level orders during construction apply, separate goal portfolios, or separate goal ledgers.

## 5. Backend Implementation

### Phase 0: Baseline and safety checks

- Run the existing backend, frontend, gateway, and streaming tests.
- Record current failures before changing code.
- Add focused regression tests proving the current zero-target problem.
- Do not change the rebalancer, OMS, broker gateway, risk engine, or ledger behaviour unless required by a failing integration test.

### Phase 1: Database models and migration

Files:

- `Backend/apps/portfolio_construction/models.py`
- new migrations under `Backend/apps/portfolio_construction/migrations/`

Tasks:

1. add `GoalInstrumentSelection`;
2. add `GoalStrategyAssignment`;
3. migrate existing `GoalStrategySelection` data:
   - create one goal-instrument row per unique goal and instrument;
   - create one assignment per old selection;
   - assign equal strategy shares when several old selections exist for the same goal-stock pair;
   - preserve enabled state, parameters, timeframe, and instance link;
4. update application code to use the new models;
5. delete `GoalStrategySelection`, its database table, old serializers, old endpoints, and unused imports in the same implementation;
6. do not keep legacy aliases or dual-write code.

### Phase 2: Construction service refactor

File:

- `Backend/apps/portfolio_construction/services.py`

Tasks:

1. split validation into instrument-selection validation and strategy-assignment validation;
2. update snapshots to store goal rows, stock-universe rows, strategy-assignment rows, and resolved policies;
3. build local goal universes from enabled stocks;
4. preserve the current one-stock and multi-stock optimization behaviour;
5. calculate stock contributions;
6. calculate strategy contributions using `strategy_share`;
7. store strategy contribution details in run metrics or a dedicated immutable JSON snapshot;
8. block apply when assignment shares are incomplete;
9. update `create_or_reuse_strategy_instances` to use aggregated non-zero target configurations;
10. update outdated disabled SHADOW instances through `update_instance`;
11. preserve idempotency and one-time apply behaviour.

### Phase 3: API changes

Files:

- `Backend/apps/portfolio_construction/views.py`
- `Backend/config/urls.py`

Replace the old selection endpoints with:

```text
GET/POST     /api/v1/portfolio-construction/goals/{goal_id}/instruments/
PATCH/DELETE /api/v1/portfolio-construction/instruments/{goal_instrument_id}/

GET/POST     /api/v1/portfolio-construction/instruments/{goal_instrument_id}/assignments/
PATCH/DELETE /api/v1/portfolio-construction/assignments/{assignment_id}/
```

Requirements:

- reuse `GET /api/v1/instruments/search/`;
- reuse `POST /api/v1/instruments/resolve/`;
- expose strategy eligibility for a goal or goal-stock selection;
- return plugin defaults and parameter schema;
- expose risk and order policies needed by the assignment form;
- reject unknown fields;
- audit every mutation;
- bump plan version after every construction input change;
- retain current CSRF and idempotency behaviour.

### Phase 4: Frontend implementation

Primary files:

- `Frontend/src/features/portfolio-builder/PortfolioBuilderPage.tsx`
- `Frontend/src/features/strategies/CreateStrategyPage.tsx`
- `Frontend/src/api/queries.ts`
- `Frontend/src/api/types.ts`

Tasks:

1. extract the IBKR search and exact-contract qualification UI from `CreateStrategyPage` into a reusable component;
2. add an **Add stock** action inside each non-`NOW` goal;
3. support IBKR search, exact contract selection, exact contract qualification, and adding the resolved instrument to the goal;
4. display stocks independently from strategies;
5. under each stock, add an assignment editor with eligible strategy, execution timeframe, schema-driven parameters, strategy share, risk policy, order policy, and create-instance toggle;
6. reuse the existing schema-driven parameter form rather than duplicating it;
7. automatically set one assignment to 100%;
8. display validation when multiple shares do not total 100%;
9. update the preview to show local goal stock weight, complete-portfolio stock contribution, strategy share, strategy-controlled portfolio weight, and aggregated instance target;
10. keep the final combined stock allocation and one net trade list unchanged.

### Phase 5: Cleanup

- remove the old `GoalStrategySelection` frontend types;
- remove old query keys and routes;
- remove duplicated instrument-search UI;
- remove unused imports and dead tests;
- update `docs/PORTFOLIO_BUILDER.md`, root `README.md`, and relevant API documentation;
- state clearly that strategies allocate ownership of constructed stock weights but do not affect Markowitz stock weighting.

## 6. Testing Plan

### 6.1 Backend unit and service tests

Add tests for:

- stock selection validation;
- assignment eligibility;
- parameter validation;
- long-only enforcement;
- strategy-share totals;
- one assignment defaulting to 1;
- multiple assignments splitting a stock correctly;
- duplicate stocks across goals;
- the same strategy identity across goals aggregating to one instance target;
- different parameters creating different instances;
- different timeframes creating different instances;
- an outdated disabled SHADOW instance being versioned and updated;
- enabled instances never being reused or modified;
- builder-created instance target weights being non-zero where stock allocation is non-zero;
- cash-only `NOW` goals;
- empty non-`NOW` goals blocking apply;
- preview and apply idempotency;
- migration correctness from old selections;
- complete removal of the old model and endpoints.

### 6.2 API tests

Test stock addition, duplicate rejection, assignment CRUD, invalid shares, rejected strategy reasons, plan-version updates, audit events, preview polling, apply polling, and idempotency conflicts.

### 6.3 Frontend tests

Test IBKR search and qualification inside Portfolio Builder, stock addition, schema parameter editing, one and multiple strategy shares, invalid share totals, preview rendering, non-zero strategy-controlled weights, and links to created strategy instances.

### 6.4 Required commands

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
cd .. && ./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

Run the repository's existing smoke tests where the environment supports them.

## 7. Acceptance Criteria

1. An operator can search and qualify a new IBKR stock without leaving Portfolio Builder.
2. A stock is added once to a goal universe, regardless of the number of assigned strategies.
3. Strategy parameters are editable from the plugin schema.
4. Multiple strategies can manage one stock using explicit shares totalling 100%.
5. Strategy selection does not accidentally alter Markowitz stock weighting.
6. Preview shows both stock-level and strategy-level weight attribution.
7. Apply still creates exactly one combined rebalance.
8. Created or reused strategy instances remain disabled in SHADOW mode.
9. Every created strategy instance has the correct non-zero `target_weight` when it controls a non-zero allocation.
10. Reused instances receive a new immutable version when their target configuration changes.
11. Duplicate strategy identities across goals are aggregated correctly.
12. The old `GoalStrategySelection` model, routes, types, and code are completely removed.
13. Existing safety boundaries remain intact.
14. All relevant backend and frontend tests pass.

## 8. Non-Goals

Do not add LIVE trading, short selling, leverage, goal-level broker accounts, goal-level cash or position ledgers, strategy return forecasts inside Markowitz, AI-based strategy selection, a research or backtesting engine, or direct order submission from Portfolio Builder.

