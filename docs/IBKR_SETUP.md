# IBKR sessions

Open **IBKR Sessions** in the operator UI, enter an IBKR username and password, and choose exactly Paper or Live. Each submission creates an isolated QCH child with a unique gateway service token, noVNC password, account mappings, portfolio routes, snapshots, and event cursor. Credentials are encrypted temporarily, consumed once, and deleted even when provisioning fails.

Paper uses TWS/API port 4002. Live uses 4001. A healthy live child that is waiting for IBKR authentication reports `WAITING_FOR_2FA`; open the noVNC link returned by the Backend and approve IBKR Mobile 2FA. A child is not reported connected until its authenticated Gateway worker says it is connected.

Deleting a session stops new commands, pauses its strategies and market subscriptions, marks its broker accounts unreconciled, asks QCH to delete the child, and retains a soft-deleted lifecycle record. It does not cancel orders already resting at IBKR.

Live order submission remains separately controlled by `ALLOW_LIVE_TRADING` and all existing kill switches, pre-trade risk checks, confirmation, order validation, idempotency, audit, and reconciliation. Test new Gateway/IBC image versions with paper sessions before allowing live orders.

The child container writes normalized `IBC_TRADING_MODE` to its mode-0600 IBC configuration. IBKR credentials are never inserted into either application database in plaintext, returned by an API, or emitted to logs.

See the root [Backend deployment guide](../README.md) for QCH variables, private-network requirements, the immutable image contract, and required platform-level access control.
