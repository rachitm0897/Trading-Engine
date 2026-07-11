# Reconciliation

Reconciliation compares internal orders, executions, positions, cash, and account state with Gateway snapshots. It runs after reconnect/startup, periodically, after uncertain submission, before re-enabling trading, and operationally at end of day.

A mismatch creates a `ReconciliationBreak` with category, severity, both values, material flag, and resolution history. An unresolved material break holds pre-trade risk. Safe repair may append missing broker executions or update a non-financial projection; it must never rewrite fills or ledgers. Other breaks require an explicit operator resolution and audit event.

Recovery sequence:

1. Gateway reconnects and blocks submission.
2. Worker refreshes accounts, positions, open orders, and executions.
3. Backend consumes ordered, idempotent events and compares state.
4. Material breaks remain blocked; clean or resolved runs set broker-reconciled state.
5. Risk reevaluates the platform gates before queued orders resume.

