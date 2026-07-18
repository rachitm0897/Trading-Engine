# Backtesting protocol

The active `BacktestProtocolVersion` stores the imported protocol and immutable configuration hash. Experiment identity includes dataset, protocol, implementation hash, feature version, instrument or universe, role, bounded parameter-space hash, date range, and provider-data version. Unchanged identities are reused; changed code, features, data, parameters, or dates create a new experiment.

The system dispatches by role:

- execution strategies use the next-bar, long-only single-asset engine;
- selectors and income models rank a point-in-time cross-section and evaluate later holdout returns;
- allocators fit on formation returns and apply weights only to a later holdout;
- overlays use only the regime available at the decision time;
- event models filter strictly on public availability;
- pair/basket models screen bounded same-peer neighbours and remain runtime-ineligible.

Single-asset research requires at least 756 valid adjusted daily bars, protects the last 126 sessions, and uses expanding walk-forward train/validation/test windows with purge and embargo gaps. Signals formed at `t` execute no earlier than `t+1` open. Commission, half-spread, square-root impact, participation, and 25/50 bps stresses are recorded. The final holdout is never used to choose parameters.

Parameter grids are never expanded without a bound. Canonical parameters are retained and remaining trials are deterministically sampled using family budgets. Trials record return, CAGR, volatility, Sharpe, Sortino, Calmar, drawdown/duration, turnover, activity, exposure, costs, capacity, subperiod/regime consistency, neighbour stability, holdout results, and deflated-Sharpe evidence. Hard rejection covers timestamp ambiguity, bad data, negative high-cost performance, excessive drawdown, inadequate activity/capacity, subperiod dependence, unstable parameters, multiple-testing failure, and unprotected holdout.

Large panels, returns, trades, pair screens, attribution, and robustness outputs are written as immutable Parquet artifacts. PostgreSQL stores identities, summaries, scores, status, and provenance. The present bundle is a current membership snapshot; results are prospective system tests unless licensed point-in-time membership, delistings, GICS, filings, and event history are supplied.
