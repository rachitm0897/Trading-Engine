# Recommendation Engine

The online path reads current cached candidate scores; it does not launch backtests in a web worker. It intersects live goal timeframe/risk rules, current dynamic eligibility, exact broker qualification, approved exact long-only implementations, compatibility, expiry, and policy. `NOW` always returns cash.

For every non-`NOW` MVP request, candidates are restricted to the exact five pilot stocks and five runtime keys, then reduced to at most one best strategy per stock. The policy uses at most five stocks, score 65, the resolved goal cash and stock caps, and at least `min(3, selected stock count)` sectors. Zero candidates produce `BLOCKED`, with precise mapping, contract, history, implementation, backtest, SHADOW-readiness, or timeframe/risk codes; it is never reported as a successful cash recommendation.

The separate sleeve optimizer assigns non-negative `x(i,k)` weights under live cash and stock caps plus sector, industry, sub-industry, strategy-family, turnover, liquidity, and capacity limits. Stock weight is the sum of its sleeves and each `strategy_share` is `x(i,k) / stock_weight(i)`. Decimal residual handling makes shares total exactly 100% per stock.

Completed runs are immutable snapshots of inputs, candidates, optimizer output, stress checks, metrics, warnings, dataset/protocol versions, and expiry. The target cached-data latency is 3â€“15 seconds; expensive work uses bounded dedicated Celery queues.

Acceptance locks the plan, goal, and run; detects plan-version conflicts; rechecks expiry, data, broker, strategy and constraints; updates existing `GoalInstrumentSelection` and `GoalStrategyAssignment`; disables replaced rows; records audit and acceptance history; and bumps plan version. It creates no strategy instance, preview, rebalance, order, or enabled strategy.

The normal Builder preview remains mandatory. `ACCEPTED_RECOMMENDATION` uses fixed accepted local weights and displays its source/run ID. Apply rechecks expiry, aggregates all goals once, invokes the existing rebalancer once, and leaves created/reused instances disabled in SHADOW. Manual edits are rejected until explicit detach.
