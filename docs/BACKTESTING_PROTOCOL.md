# Backtesting Protocol

The active `BacktestProtocolVersion` stores `backtest_spec.json` and its configuration hash. Research interfaces are explicit for single-asset execution, cross-sectional selection, allocation, overlays, timestamped events, and pair/basket research. Pair/basket cannot emit a single-instrument runtime target.

Daily signals use data through bar `t` and trade no earlier than `t+1`. The engine supports next-open fills, commission, half-spread, square-root impact, participation limits, and 5/10/25/50 bps stress. Long-only actionable runs reject negative exposures. Returns, trades, features, and attribution belong in immutable Parquet artifacts, not PostgreSQL JSON blobs.

Walk-forward helpers support rolling or expanding train/validation/test windows, explicit purge and embargo gaps, deterministic parameter budgets, and an untouched final holdout flag. Robustness utilities cover bootstrap intervals, neighboring-parameter stability, deflated Sharpe, probability of backtest overfitting, and Benjamini-Hochberg false-discovery control. Every sampled parameter trial is recorded; oversized grids are deterministically sampled after retaining a baseline.

The current bundle is only a present-day membership snapshot. Historical testing is valid only when the data source supplies point-in-time membership, delistings and returns, historical GICS, revisions, filing/publication timestamps, and exact event availability. Otherwise results are prospective system tests and must be labelled as such.
