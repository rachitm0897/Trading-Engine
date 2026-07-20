# Local development

1. Copy `.env.example` to `.env`; replace local tokens and passwords.
2. Run `docker compose up --build -d`.
3. Wait for `docker compose ps` to show all services healthy.
4. Inspect logs with `docker compose logs -f backend ib_gateway frontend`.
5. Stop with `docker compose down`. Add `-v` only when intentionally discarding all local database and Gateway state.

Validate the complete private Kafka/Flink topology and restart recovery with:

```powershell
powershell -NoProfile -File docs/compose_smoke.ps1
powershell -NoProfile -File docs/streaming_recovery_smoke.ps1
```

Compose's `ib_gateway` is an explicitly local/static compatibility service using the real `ib_async` adapter and `${IBC_TRADING_MODE:-paper}`. Configure its credentials in the root `.env` only when testing legacy local flows. Backend production logic has no global gateway route; managed sessions require the QCH injected variables and published `IBKR_GATEWAY_IMAGE` described in [QFS deployment](QFS_DEPLOYMENT.md). Until IBKR authentication completes, broker health stays disconnected and risk correctly blocks submissions.

The static compatibility route is enabled only by `BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED=true` in Compose. Never enable it in production. PostgreSQL and Redis are reachable only on the private Compose network and are not published to the host.

For host-side tests, use a separate Python environment per Python application because both intentionally own their dependencies. SQLite is the automatic test database.

Health checks:

```text
GET http://localhost:5173/healthz
GET http://localhost:8000/healthz
GET http://localhost:8080/healthz
```
