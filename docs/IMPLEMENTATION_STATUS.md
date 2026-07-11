# Implementation status

Updated 2026-07-11.

| Area | Status | Notes |
|---|---|---|
| Three-application/Compose bootstrap | Implemented | One exposed port per application; PostgreSQL and Redis private. |
| Gateway one-port runtime | Implemented | Nginx, noVNC, Supervisor, IBC, Gateway, Django, and broker worker included. |
| Gateway command/event durability | Implemented | SQLite WAL, idempotent commands, ordered events, acknowledgement, mock/ib_async adapters. |
| Backend financial domain | Implemented | Core models, ledgers, audit/outbox, OMS, fills, risk, reconciliation records. |
| Strategies and allocation | Implemented | Exactly five engines, reproducible run hash, aggregation, lot rounding, notional suppression. |
| Frontend | Implemented | Ten terminal windows, Backend-only data access, QFS base path, controls and status. |
| Automated unit tests | Implemented | Backend, Gateway, and Frontend suites use mocks and no real IBKR account. |
| Real IBKR validation | Operator required | Requires paper credentials, 2FA, subscriptions, and contract universe. |
| Production hardening | Partially implemented | See limitations/open questions for calendars, HA, alerting, and policy values. |

Final verification on 2026-07-11:

- Backend: 16 tests passed.
- Gateway: 9 tests passed.
- Frontend: 4 tests passed; TypeScript and Vite production build passed; production dependency audit reported zero vulnerabilities.
- `docker compose up --build -d`: passed from clean volumes; all five services healthy.
- Live mock contract: place, modify, and cancel commands completed and emitted ordered Gateway events.
- Gateway security: unauthenticated API returned 401; only port 8080 was published; no raw TWS/VNC listener was exposed.
- Real paper verification: IB Gateway 1045 ran under IBC, noVNC displayed the connected Gateway window, API client 17 connected, and real IBKR account values and positions synchronized into PostgreSQL. Demo/test database and Gateway volumes were removed before verification.
