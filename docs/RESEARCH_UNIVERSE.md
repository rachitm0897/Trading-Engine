# Research universe

`Trading_Engine_Stock_Strategy_Universe_JSON/` is the trusted source bundle: exactly 500 current US large-cap members, 97 strategy definitions, and the complete 11/25/74/163 GICS hierarchy. It is a current snapshot, not historical membership, so it must not be represented as survivorship-free history.

## Activate and bootstrap

```powershell
cd Backend
..\.venv\Scripts\python.exe manage.py validate_research_bundle ..\Trading_Engine_Stock_Strategy_Universe_JSON
..\.venv\Scripts\python.exe manage.py import_research_bundle ..\Trading_Engine_Stock_Strategy_Universe_JSON --activate
..\.venv\Scripts\python.exe manage.py bootstrap_recommendation_system
```

Validation checks schemas, manifest sizes and SHA-256 hashes, fixed counts, taxonomy paths, enum values, symbols, CIKs, and all 97 registry entries. Import is transactional and idempotent, retires the previous active version, registers every explicit implementation, and never evaluates formula text from JSON.

Issuer identity uses CIK; instrument identity remains exchange/currency/symbol. Mapping is batched and failure-isolated. Finnhub mappings must be verified. IBKR contracts are qualified separately through the authenticated Gateway; Backend never connects to TWS directly. Background qualification covers the universe, while the online path rechecks and substitutes finalists only.

## Data and provenance

Research storage is versioned and point-in-time:

- ten years of adjusted and raw daily OHLCV, dividends, splits, total-return close, provider and revision timestamps;
- up to 90 days of required 1m/5m/15m/1h IBKR history plus trading schedules;
- corporate actions;
- reported fundamentals with filing/public-availability timestamps and revisions;
- analyst recommendations and estimates without backdating retrieval time;
- earnings and other events with explicit availability and effective timestamps;
- per-member coverage summaries and current eligibility.

Daily refresh uses a revision overlap instead of re-downloading ten years. Finnhub is primary for daily research data; exact-contract IBKR `ADJUSTED_LAST` is the bounded fallback. Intraday refresh likewise uses incremental verified Finnhub candles first and exact-contract IBKR `TRADES` plus historical schedules as fallback. Structural OHLCV validation, freshness, session coverage, provider identity, corporate-action reconciliation, and the minimum 756 valid daily bars are explicit.

Feature snapshots carry as-of time, availability time, provider-data version, implementation version, and Parquet artifact URI. Point-in-time queries exclude records published after the simulated decision. Fundamental or event strategies remain unavailable when licensed historical timestamps are absent; the service does not backfill guessed timestamps.

Research administration remains internal through Django admin, commands, audit events, structured logs, and `/metrics`. The normal frontend intentionally has no Research route. Existing read-only research APIs remain for operator compatibility; activation, overrides, scheduling, and promotion remain trusted command operations.
