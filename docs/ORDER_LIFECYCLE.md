# Order lifecycle

An order starts as an `OrderIntent` created by rebalancing or an approved operator workflow. Risk produces `APPROVED`, `RESIZED`, `HELD`, or `REJECTED` records. Only approved quantity becomes an OMS order.

```text
CREATED -> RISK_APPROVED -> QUEUED -> SUBMITTED -> ACKNOWLEDGED
                                            |          |
                                            +-> PARTIALLY_FILLED -> FILLED
                                            +-> CANCEL_PENDING -> CANCELLED
                                            +-> REJECTED / EXPIRED / UNKNOWN
```

Every transition is append-only in `OrderStatusHistory`. Gateway commands carry unique idempotency keys. Broker order and permanent IDs never replace internal IDs. Only execution callbacks create fills; status callbacks alone cannot infer a fill. Each accepted fill atomically updates order totals, creates immutable cash and position ledger entries, and updates the current position projection. Repeated execution IDs are ignored.

`UNKNOWN` and `BROKER_BLOCKED` stop new submission until reconciliation establishes broker truth.

