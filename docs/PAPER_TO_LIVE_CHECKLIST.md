# Paper-to-live checklist

- [ ] Paper trading has completed at least one full operational cycle including reconnect and end-of-day reconciliation.
- [ ] Order placement, modification, cancellation, partial fills, commissions, and broker rejection paths are verified.
- [ ] Contract qualification, lot sizes, ticks, currencies, exchanges, and session rules are verified for the production universe.
- [ ] Cash, buying power, exposure, concentration, turnover, loss, pacing, and price-freshness limits are configured.
- [ ] Global, account, portfolio, and strategy kill switches are tested.
- [ ] noVNC, QFS secrets, TLS, service token, logs, backups, alerting, and persistent volumes are secured.
- [ ] No material reconciliation break exists and Gateway reports broker state reconciled.
- [ ] `IBC_TRADING_MODE=live` and `ALLOW_LIVE_TRADING=true` are changed by two-person operational approval.
- [ ] `GLOBAL_KILL_SWITCH=false`, account/strategy switches are clear, and a small live canary order is approved.

If any condition becomes false, stop submission and return to paper/block mode.

