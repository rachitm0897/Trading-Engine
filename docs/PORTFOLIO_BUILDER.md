# Portfolio Builder

Portfolio Builder divides one broker-backed `TradingPortfolio` into up to ten virtual goal slices. Goals are construction inputs; they do not own cash, positions, fills, orders, or ledgers.

## Normal workflow

The `/portfolio-builder` frontend has three steps:

1. **Goals** — name, allocation percentage, timeframe, risk, and enabled status. Enabled allocations must total exactly 100%. One button saves every goal and generates the complete plan recommendation.
2. **Recommendations** — grouped goal cards show symbol/company, fixed stock weight, one primary strategy and its timeframe, goal timeframe/risk, expected return/volatility/drawdown, and a short reason. The only actions are regenerate, preview, or return to goals. There is no stock search, strategy editor, ownership form, accept, detach, readiness matrix, or dataset/protocol display.
3. **Preview & Apply** — preview merges goal contributions, duplicate stocks, strategy targets, cash, metrics, current/proposed weights, and one net trade list. Apply requires a separate explicit confirmation.

NOW remains 100% cash. For other profiles, the backend selects 5–20 names according to timeframe/risk, qualifies or substitutes exact IBKR finalists, enforces the live cash/stock rules and GICS/turnover constraints, fixes one 100% strategy share per stock, attaches all goals atomically, and bumps the plan version once.

## Safety boundary

Recommendation generation only updates construction metadata and immutable recommendation/audit records. It creates no order, rebalance, strategy instance, or enablement. Preview creates no order. Apply invokes the existing combined rebalancer exactly once; sizing, price provenance, cash/fee buffers, risk, sell-before-buy ordering, OMS, Gateway, ledgers, kill switch, and reconciliation remain mandatory. Any created/reused strategy instance is disabled in SHADOW, and LIVE configuration is rejected at startup.

The advanced manual target optimizer remains available on the Portfolio page. Backend manual construction endpoints remain for compatibility/internal tools but are intentionally absent from the standard Builder UI.

## API

```text
GET/POST     /api/v1/portfolio-construction/plans/
GET/PATCH    /api/v1/portfolio-construction/plans/{plan_id}/
POST         /api/v1/portfolio-construction/plans/{plan_id}/goals/
PATCH/DELETE /api/v1/portfolio-construction/goals/{goal_id}/
POST         /api/v1/portfolio-construction/plans/{plan_id}/recommendations/
GET          /api/v1/portfolio-construction/recommendation-batches/{batch_id}/
POST         /api/v1/portfolio-construction/preview/
GET          /api/v1/portfolio-construction/runs/{run_id}/
POST         /api/v1/portfolio-construction/runs/{run_id}/apply/
```

Recommendation, preview, and apply POSTs require `Idempotency-Key`. Preview and apply runs are polled to terminal status. A failed preview is never rendered as an empty successful allocation.
