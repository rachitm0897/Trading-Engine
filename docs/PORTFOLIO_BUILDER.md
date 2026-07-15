# Portfolio Builder

Portfolio Builder is a deterministic, paper-only workflow for dividing one broker-backed `TradingPortfolio` into up to ten virtual goal slices. Goals are construction inputs only: they do not own cash, positions, fills, orders, or financial ledgers.

## Workflow

The frontend route is `/portfolio-builder` and has four steps:

1. Allocate enabled goals. Each row has a name, percentage, fixed timeframe bucket, and filtered risk level. Enabled percentages must total exactly 100% before preview or apply.
2. Search IBKR, select an exact contract, qualify it, and add the resolved stock once to a goal universe. Assign one or more eligible strategies under that stock. Parameters come from the plugin schema, and enabled instance-creating assignments must divide the stock with explicit shares totalling exactly 100%.
3. Preview local stock weights, complete-portfolio stock contributions, strategy-controlled portfolio weights, aggregated instance targets, current-versus-proposed weights, metrics, and one net rebalance trade list.
4. Confirm once. The combined stock target enters the existing SHADOW or PAPER rebalance pipeline. Matching strategy instances are created or updated in disabled `SHADOW` mode and must be reviewed before they can be enabled.

The existing single-universe optimizer remains available on the Portfolio page as **Advanced target optimizer**.

## Fixed goal rules

Timeframes are `NOW`, `HURRY`, `FAST`, `BUILD`, `GROW`, and `COMPOUND`. Risk levels are 1 through 5 (`PRESERVATION` through `AGGRESSIVE`). The backend repeats the frontend timeframe-risk validation.

Goal cash is the larger of the fixed timeframe cash floor and risk cash floor. Risk also fixes the maximum local single-stock weight. Risk levels 1–3 use `MINIMUM_VARIANCE`; levels 4–5 use `MAXIMUM_SHARPE`. `NOW` is intentionally 100% cash. Optimization uses 252 trading days, requires at least 60 aligned observations, and remains stock-only, long-only, and unlevered.

Edge behavior is explicit:

- no selected stocks previews as cash with a warning; a non-`NOW` goal blocks apply;
- one stock is capped by the goal's single-stock limit and the remainder stays cash;
- two or more stocks use the same Markowitz solver as the advanced optimizer;
- duplicate stocks across goals are merged using `goal allocation × local stock weight`.

## Stock construction and strategy ownership

Stocks and strategies are intentionally separate inputs. `GoalInstrumentSelection` defines the optimizer universe. Adding, removing, or changing strategy assignments does not change Markowitz stock weighting.

For goal `g` and stock `i`, the complete-portfolio stock contribution is `P(g,i) = goal allocation × local optimizer weight`. For assignment `k`, the controlled portfolio weight is `T(g,i,k) = P(g,i) × strategy share`. Assignments with the same strategy definition, instrument, timeframe, validated parameter hash, risk policy, and order policy aggregate across goals into one instance target.

Every applied instance receives an explicit configuration:

```json
{
  "target_weight": "<aggregated strategy weight>",
  "capital_share": "<aggregated strategy weight>",
  "priority": 100,
  "construction_run_id": "<run id>"
}
```

Only a disabled `SHADOW` instance with the exact identity may be reused. If its target changed, the normal update workflow creates a new immutable strategy version. Enabled, `PAPER`, `OBSERVE`, and otherwise incompatible instances are never modified. Builder apply always leaves created or updated instances disabled in `SHADOW` mode.

Deleting a Builder-created strategy clears the assignment's nullable instance backlink while preserving the stock, strategy definition, parameters, and ownership share. A later Builder apply may therefore create a fresh disabled `SHADOW` instance; the backlink is construction metadata and does not block normal strategy deletion.

## API

All responses use the standard envelope. Mutations retain the application's CSRF behavior and preview/apply require `Idempotency-Key`.

```text
GET/POST  /api/v1/portfolio-construction/plans/
GET/PATCH /api/v1/portfolio-construction/plans/{plan_id}/
POST      /api/v1/portfolio-construction/plans/{plan_id}/goals/
PATCH/DELETE /api/v1/portfolio-construction/goals/{goal_id}/
GET       /api/v1/portfolio-construction/goals/{goal_id}/eligible-strategies/
GET/POST  /api/v1/portfolio-construction/goals/{goal_id}/instruments/
PATCH/DELETE /api/v1/portfolio-construction/instruments/{goal_instrument_id}/
GET/POST  /api/v1/portfolio-construction/instruments/{goal_instrument_id}/assignments/
PATCH/DELETE /api/v1/portfolio-construction/assignments/{assignment_id}/
GET       /api/v1/instruments/search/
POST      /api/v1/instruments/resolve/
GET       /api/v1/strategy-policies/
POST      /api/v1/portfolio-construction/preview/
GET       /api/v1/portfolio-construction/runs/
GET       /api/v1/portfolio-construction/runs/{run_id}/
POST      /api/v1/portfolio-construction/runs/{run_id}/apply/
```

Preview and apply return `202 Accepted` while queued. Poll the construction run until `status` is `COMPLETED` or `FAILED`, then poll `application_status` until `APPLIED` or `FAILED`. Retryable failures require the original key and `Idempotency-Retry: true`.

A failed preview is not a usable preview result. The UI remains on the stock-and-strategy step and displays the run's `last_error`; it never renders a failed run as an empty allocation. Preview requires sufficient recent Finnhub history, so an unconfigured provider is reported explicitly and must be configured from the System page before retrying.

## Persistence and safety boundary

`PortfolioConstructionRun` stores immutable plan, goal, stock-universe, strategy-assignment, and resolved-policy snapshots plus local results, strategy contribution details, aggregated instance targets, combined stock targets, warnings, retry state, and its optional applied rebalance. `PortfolioConstructionTarget` stores only final combined stock targets and goal contribution explanations. There are no goal-level cash or position ledgers.

The rebalancer identifies these targets with `GOAL_CONSTRUCTION` and remains responsible for current positions, auditable prices, drift, cash and fee buffers, lots, minimum trades, final turnover, sell-before-buy sequencing, position sizing, risk checks, OMS, and paper execution. Portfolio Builder cannot configure LIVE mode, short selling, or leverage, and it never enables strategy instances automatically.
