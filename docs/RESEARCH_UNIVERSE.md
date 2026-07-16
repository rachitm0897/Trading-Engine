# Research Universe

`Trading_Engine_Stock_Strategy_Universe_JSON/` is the repository source bundle. It contains a current 500-stock snapshot, the full public 11/25/74/163 GICS transcription, 97 strategy hypotheses, compatibility rules, and a backtest protocol. The stock list is not historical membership and must not be used for a survivorship-unbiased historical claim.

## Import

Trusted operators run:

```powershell
cd Backend
..\.venv\Scripts\python.exe manage.py validate_research_bundle ..\Trading_Engine_Stock_Strategy_Universe_JSON
..\.venv\Scripts\python.exe manage.py import_research_bundle ..\Trading_Engine_Stock_Strategy_Universe_JSON --activate
```

Validation checks required files, byte sizes, SHA-256 hashes, repository JSON Schemas, fixed counts, GICS parent paths, stock sub-industries, unique symbols/CIKs/strategy IDs, representative-share exclusions, scopes, and frequencies. Import runs in one transaction, rejects changed content under the same version, is idempotent for the same manifest, and atomically retires the prior active version.

Issuers use CIK identity; ticker remains instrument identity. Deterministic mapping reuses `Instrument` and `InstrumentProviderMapping`, creates only an unqualified canonical instrument when unambiguous, and never creates a `BrokerContract`. Exact IBKR qualification remains an operator-controlled separate gate. Research eligibility requires verified provider data; Builder eligibility additionally requires an exact qualified broker contract.

Operational `InstrumentPriceHistory.adjusted_close` is not silently upgraded to research-grade data. Staging copies are `SUSPECT` until raw/adjusted OHLC, dividends, splits, total-return close, delistings, timestamps, and revisions reconcile. Fundamentals and events are queried only at or after public availability. Unknown event timing becomes next-session availability.

Read-only APIs are paginated:

- `/api/v1/research/dataset-versions/`
- `/api/v1/research/universes/` and `universes/{id}/members/`
- `/api/v1/research/strategies/` and `strategies/{research_id}/`
- `/api/v1/research/readiness/`
- `/api/v1/research/candidate-scores/`
- `/api/v1/research/experiments/{id}/`

Bundle activation, provider overrides, experiment scheduling, approval, and promotion remain management-command operations because default API authentication is not yet a safe administrative boundary.
