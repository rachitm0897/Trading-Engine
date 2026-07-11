# Open questions and assumptions

The implementation proceeds with these safe defaults:

- Base currency is USD until account synchronization supplies the broker value.
- Local Compose and QFS use `ib_async` in paper mode; the mocked adapter is restricted to automated tests.
- Decimal quantities support fractional shares, while each instrument's configured lot size controls rounding.
- Strategy configurations carry their own version; changing parameters should create a new version operationally.
- Controlled 15-second polling is used for the first frontend release rather than SSE.
- Sector limits apply only where instrument sector metadata exists.
- New flow/rebalance execution defaults to `SHADOW`; `PAPER` must be selected explicitly and live is rejected.
- A portfolio flow represents settled cash; approved strategy-capital changes commit atomically with the run and outbox fact.
- Corrected bars are new deterministic `(bar_id, version)` final facts; strategies use final bars by default.
- Local Kafka uses six partitions and single-node replication; production topology and retention require capacity planning.
- Initial indicator parameters are SMA 20/50, RSI 14, Donchian 20, momentum 20, realized volatility 20 and average volume 20.
- `INSTRUMENT_SYMBOL_MAP` is the controlled Flink symbol-to-instrument-ID map for the local deployment.
- Missing conviction/liquidity/cost metadata falls back to strategy priority and stable IDs for deterministic liquidation ordering.
- Rebalance cost benefit initially uses the policy fee buffer plus five basis points of notional.
- Sizing previews take broker restrictions and ADV as explicit auditable inputs until connected reference feeds are certified.

Before live use, operators must decide:

- authoritative exchange calendar/holiday and stale-price thresholds;
- account-specific margin, commission, concentration, turnover, and loss limits;
- how IBKR Financial Advisor allocations or multiple accounts should map to portfolios;
- alert channels and escalation owners for Gateway disconnects and material breaks;
- backup retention and recovery objectives for PostgreSQL and Gateway event storage;
- whether QFS strips prefixes in each environment (both are routed, but canonical redirects should match the proxy);
- approved IB Gateway/IBC upgrade cadence and paper certification procedure.
- production Kafka replication, retention, encryption/authentication and alert thresholds;
- production Flink parallelism, checkpoint retention/storage and upgrade runbook;
- ownership and deployment of the canonical instrument symbol map;
- authoritative conviction, liquidity, tax-lot and transaction-cost inputs for liquidation policies;
- whether accepted flows need second approval before strategy capital becomes effective;
- paper promotion criteria for `NEW_EXECUTION_MODE=SHADOW` to become `PAPER`.
