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

The strategy layer is plugin-based. The initial registered definitions are fixed-weight rebalance, SMA crossover, RSI mean reversion, Donchian breakout, and volatility-target momentum; additional reviewed plugins use the same interface. A `StrategyDefinition` describes the plugin, a `StrategyInstance` binds it to one canonical instrument/portfolio/configuration, and every material edit creates an immutable `StrategyVersion`.

Active instances publish de-duplicated bar, indicator, parameter, and warm-up requirements to `strategy.inputs.v1`. Flink uses that registry to build requested instrument/timeframe bars and parameter-hashed indicators. Final persisted inputs invoke the plugin with versioned isolated state. Plugins return only signals and the common `StrategyTarget`; they cannot submit orders. Multiple instance targets are netted at portfolio/instrument level and every contribution/version is retained on the single resulting order intent.
