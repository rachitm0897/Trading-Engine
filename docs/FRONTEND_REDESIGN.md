# Frontend redesign

## Operator walkthrough

The left navigation now has five stable routes: Dashboard, Strategies, Portfolio, Orders & Activity, and System. The top bar carries the selected account and portfolio across every page and shows the paper operating state.

1. Open **Strategies** and choose **Create strategy**.
2. Enter any ticker and exchange; contract qualification is shown as not checked, pending, or qualified with its conId.
3. Choose a definition and timeframe supplied by the Backend. Parameter fields are generated from its `parameter_schema`.
4. Configure target weight, capital share, priority, execution mode, and optional policies. `SHADOW` is the default, advanced policies are collapsed, and `LIVE` is absent.
5. Review the readable configuration and create immutable version 1.
6. The detail view traces persisted bars and indicators alongside signal, target, order, and fill markers. Overview shows warm-up, target, attributed quantity, and active order; Activity shows the execution timeline.
7. Portfolio exposes holdings and allocation first, with flows, rebalance preview, sizing, and policy internals in advanced sections.
8. Orders & Activity combines the blotter, fill progress, executions, and audit events. The order drawer exposes modify/cancel only in Backend-supported states. The manual ticket remains an advanced operator action.
9. System consolidates Gateway/noVNC, streaming health, reconciliation, risk, and audit. The global kill switch requires a reason and explicit confirmation.

## Backend additions

- `GET /api/v1/dashboard/summary/` returns a portfolio-scoped operating summary and attention items. Gateway failure is represented as partial data rather than hiding the remaining summary.
- `GET /api/v1/portfolios/series/` returns real persisted market-bar/current-holding mark-to-market series and a current broker snapshot fallback. No production chart series is hardcoded.
- `GET /api/v1/strategy-instances/:id/chart/` returns persisted bars, indicators, signals, targets, orders, and fills.
- Orders, executions, audit, and reconciliation accept additive filters/limits while preserving their existing data envelopes; paged list endpoints add `count`, `limit`, and `offset` metadata.

## Current data limitation

Until durable valuation snapshots or TimescaleDB-backed portfolio history are available, historical portfolio series apply current holdings to persisted historical bars and anchor the latest value to broker NAV. The endpoint declares this source as `POSTGRES_MARKET_BARS_WITH_CURRENT_HOLDINGS`; it is useful for operator context but is not a tax-lot or point-in-time performance record.

The production gaps in authentication/authorization, deployment isolation certification, TimescaleDB history, alerting, and real IBKR paper/live certification remain unchanged. Configurable strategy APIs still reject `LIVE`.
