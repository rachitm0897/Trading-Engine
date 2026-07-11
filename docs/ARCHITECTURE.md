# Architecture

```text
Browser -> Frontend -> Backend -> authenticated Gateway REST API
                         |                   |
                  PostgreSQL/Redis     SQLite WAL buffer
                                             |
                                      sole ib_async worker
                                             |
                                     localhost TWS socket
```

The Backend is the financial source of truth. PostgreSQL stores orders, executions, positions, cash/position ledger entries, risk decisions, outbox events, audit events, and reconciliation. Redis transports Celery work only. The Gateway SQLite database provides command idempotency and ordered callback buffering across restarts; it is not an accounting ledger.

The execution pipeline is:

```text
StrategyRun -> StrategyTarget -> allocation aggregation -> RebalanceRun
-> OrderIntent -> RiskCheckResult -> OMS Order -> outbox/Gateway command
-> IBKR execution event -> Fill -> cash/position ledgers -> reconciliation
```

Only the dedicated Gateway broker worker imports and owns `ib_async`. Nginx is the Gateway's sole public listener and routes API, noVNC, websockify, and health traffic. Supervisor runs the fixed process set; there is no Docker socket or dynamic container control.

The exactly five strategy implementations are fixed-weight rebalance, SMA trend, RSI mean reversion, Donchian breakout, and volatility-target momentum. They return target weights and cannot submit orders.

