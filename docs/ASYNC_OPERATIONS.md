# Asynchronous operations

The API keeps expensive solvers, history downloads, and long-running workflows outside Gunicorn request workers. A queued request returns `202 Accepted` in the standard response envelope. Clients should retain the operation ID and poll the listed resource until it reaches a terminal status.

| Operation | Submit endpoint | Poll endpoint | Terminal status |
| --- | --- | --- | --- |
| Optimization preview | `POST /api/v1/portfolio-optimization/preview/` | `GET /api/v1/portfolio-optimization/runs/{id}/` | `COMPLETED` or `FAILED` |
| Optimization application | `POST /api/v1/portfolio-optimization/run/` | `GET /api/v1/portfolio-optimization/runs/{id}/` | `APPLIED` or `FAILED` in `application_status` |
| Optimization-backed flow | `POST /api/v1/allocations/flows/` | `GET /api/v1/allocations/runs/{id}/` | `COMPLETED`, `PARTIALLY_ALLOCATED`, or `FAILED` |
| Rebalance | `POST /api/v1/rebalancing/preview/` or `POST /api/v1/rebalancing/run/` | `GET /api/v1/rebalancing/runs/{id}/` | `COMPLETED`, `PARTIALLY_COMPLETED`, `BLOCKED`, or `FAILED` |
| Kafka replay | `POST /api/v1/streaming/replay/` | `GET /api/v1/streaming/replay/{id}/` | `COMPLETED` or `FAILED` |

Every mutating operation that requires idempotency rejects a missing `Idempotency-Key`. Reusing a key with a different canonical request returns a conflict. Retrying a persisted retryable failure requires the original key and `Idempotency-Retry: true`; uncertain broker submissions are reconciled rather than blindly resubmitted.

All execution remains paper or shadow only. The worker paths do not enable live trading.
