# Open questions and assumptions

The implementation proceeds with these safe defaults:

- Base currency is USD until account synchronization supplies the broker value.
- Local Compose and QFS use `ib_async` in paper mode; the mocked adapter is restricted to automated tests.
- Decimal quantities support fractional shares, while each instrument's configured lot size controls rounding.
- Strategy configurations carry their own version; changing parameters should create a new version operationally.
- Controlled 15-second polling is used for the first frontend release rather than SSE.
- Sector limits apply only where instrument sector metadata exists.

Before live use, operators must decide:

- authoritative exchange calendar/holiday and stale-price thresholds;
- account-specific margin, commission, concentration, turnover, and loss limits;
- how IBKR Financial Advisor allocations or multiple accounts should map to portfolios;
- alert channels and escalation owners for Gateway disconnects and material breaks;
- backup retention and recovery objectives for PostgreSQL and Gateway event storage;
- whether QFS strips prefixes in each environment (both are routed, but canonical redirects should match the proxy);
- approved IB Gateway/IBC upgrade cadence and paper certification procedure.
