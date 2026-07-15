# Portfolio Builder

Portfolio Builder is a deterministic, paper-only workflow for dividing one broker-backed `TradingPortfolio` into up to ten virtual goal slices. Goals are construction inputs only: they do not own cash, positions, fills, orders, or financial ledgers.

## Workflow

The frontend route is `/portfolio-builder` and has four steps:

1. Allocate enabled goals. Each row has a name, percentage, fixed timeframe bucket, and filtered risk level. Enabled percentages must total exactly 100% before preview or apply.
2. Select eligible strategy-stock pairs separately for each goal. Ineligible implemented strategies remain visible with a rejection reason. Parameters and execution timeframes use the existing strategy plugin schemas.
3. Preview each local goal target, the weighted combined allocation, current-versus-proposed weights, metrics, and one net rebalance trade list.
4. Confirm once. The combined target enters the existing SHADOW or PAPER rebalance pipeline. Matching strategy instances are created or reused in disabled `SHADOW` mode and must be reviewed before they can be enabled.

The existing single-universe optimizer remains available on the Portfolio page as **Advanced target optimizer**.

## Fixed goal rules

Timeframes are `NOW`, `HURRY`, `FAST`, `BUILD`, `GROW`, and `COMPOUND`. Risk levels are 1 through 5 (`PRESERVATION` through `AGGRESSIVE`). The backend repeats the frontend timeframe-risk validation.

Goal cash is the larger of the fixed timeframe cash floor and risk cash floor. Risk also fixes the maximum local single-stock weight. Risk levels 1–3 use `MINIMUM_VARIANCE`; levels 4–5 use `MAXIMUM_SHARPE`. `NOW` is intentionally 100% cash. Optimization uses 252 trading days, requires at least 60 aligned observations, and remains stock-only, long-only, and unlevered.

Edge behavior is explicit:

- no selected stocks previews as cash with a warning; a non-`NOW` goal blocks apply;
- one stock is capped by the goal's single-stock limit and the remainder stays cash;
- two or more stocks use the same Markowitz solver as the advanced optimizer;
- duplicate stocks across goals are merged using `goal allocation × local stock weight`.

## API

All responses use the standard envelope. Mutations retain the application's CSRF behavior and preview/apply require `Idempotency-Key`.

```text
GET/POST  /api/v1/portfolio-construction/plans/
GET/PATCH /api/v1/portfolio-construction/plans/{plan_id}/
POST      /api/v1/portfolio-construction/plans/{plan_id}/goals/
PATCH/DELETE /api/v1/portfolio-construction/goals/{goal_id}/
GET       /api/v1/portfolio-construction/goals/{goal_id}/eligible-strategies/
GET/POST  /api/v1/portfolio-construction/goals/{goal_id}/selections/
DELETE    /api/v1/portfolio-construction/selections/{selection_id}/
POST      /api/v1/portfolio-construction/preview/
GET       /api/v1/portfolio-construction/runs/
GET       /api/v1/portfolio-construction/runs/{run_id}/
POST      /api/v1/portfolio-construction/runs/{run_id}/apply/
```

Preview and apply return `202 Accepted` while queued. Poll the construction run until `status` is `COMPLETED` or `FAILED`, then poll `application_status` until `APPLIED` or `FAILED`. Retryable failures require the original key and `Idempotency-Retry: true`.

## Persistence and safety boundary

`PortfolioConstructionRun` stores immutable plan, goal, selection, and resolved-policy snapshots plus local results, combined targets, warnings, retry state, and its optional applied rebalance. `PortfolioConstructionTarget` stores only final combined stock targets and goal contribution explanations. There are no goal-level cash or position ledgers.

The rebalancer identifies these targets with `GOAL_CONSTRUCTION` and remains responsible for current positions, auditable prices, drift, cash and fee buffers, lots, minimum trades, final turnover, sell-before-buy sequencing, position sizing, risk checks, OMS, and paper execution. Portfolio Builder cannot configure LIVE mode, short selling, or leverage, and it never enables strategy instances automatically.

