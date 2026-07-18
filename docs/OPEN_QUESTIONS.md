# Open questions and assumptions

Implemented safe defaults:

- the bundle supplies current 500-member/GICS membership only; no survivorship-free claim is made;
- Finnhub is primary for incremental daily and intraday prices, corporate actions, fundamentals, estimates, and events; exact-contract IBKR is the bounded daily and intraday fallback;
- provider retrieval time is used when historical publication time is unavailable, preventing backdating at the cost of less historical coverage;
- research requires at least 756 valid daily bars; required intraday windows are bounded to 90 days;
- missing optional role data removes that role's contribution and moves recommendations through explicit fallback tiers;
- final IBKR qualification is lazy with ranked substitution, while background batches progressively qualify the full universe;
- the normal frontend exposes neither Research administration nor manual recommendation acceptance;
- generation and preview have no execution side effects; apply is explicit and remains SHADOW/PAPER only;
- short and pair/basket runtime execution are disabled until borrow/cost data and atomic multi-instrument targets exist;
- PostgreSQL stores state and summaries; large research artifacts use the configured filesystem/Parquet store;
- operator observability is through admin, audit, structured logs, and `/metrics`.

Before production certification, operators must decide:

- licensed sources for point-in-time historical index membership, delistings, GICS, filings, estimate revisions, and exact event timestamps;
- authoritative exchange calendars, holiday coverage, stale thresholds, and corporate-action reconciliation SLAs;
- an S3-compatible immutable artifact backend, retention, encryption, backup, and recovery objectives;
- research queue capacity, nightly/weekly/monthly throughput targets, and alert ownership;
- account-specific margin, commission, tax-lot, concentration, turnover, liquidity, and loss limits;
- the paper evidence and second-approval policy required to move a strategy from SHADOW validation to PAPER enablement;
- production Kafka/Flink replication, checkpoints, retention, symbol-map ownership, and upgrade procedures;
- whether a future multi-instrument plugin needs atomic portfolio targets and a dedicated net-order policy resolver;
- authenticated operator roles before exposing dataset activation, scheduling, overrides, or promotion as mutation APIs.

Until the relevant licensed data exists, affected historical experiments fail safely or remain unpromoted; the engine does not manufacture availability timestamps, scores, contracts, or SHADOW evidence.
