# IBKR setup

1. Use a dedicated IBKR paper account and client ID.
2. Set `IBC_TRADING_MODE=paper`, `BROKER_ADAPTER=ib_async`, `IBKR_CLIENT_ID`, and secret credentials.
3. Open the Gateway noVNC URL, authenticate, and approve IBKR Mobile 2FA.
4. In IB Gateway API settings, use socket 4002 for paper (4001 for live), disable read-only only when order testing is intended, restrict trusted IPs to localhost, and configure the worker client ID as master when appropriate.
5. Verify Gateway reports connected but remains blocked until the first state refresh/reconciliation completes.

IB Gateway is a GUI-authenticated application and must be restarted periodically. IBC handles login dialogs and the configured restart window, but operators remain responsible for 2FA and IBKR session policies. The container build pins IBC 3.23.0 and installs the stable standalone Gateway; validate both in paper before promoting a new image.

Credentials are read from environment secrets into a mode-0600 runtime IBC file, never inserted into either database, returned by an API, or emitted to logs.

