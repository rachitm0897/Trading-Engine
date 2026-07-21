# Local development

1. Copy `.env.example` to `.env`; replace local tokens and passwords.
2. Start the infrastructure services and wait for PostgreSQL, Redis, and Kafka to become healthy. `kafka-init` should exit successfully after creating topics; the Flink services should remain running.

   ```bash
   docker compose up -d postgres redis kafka kafka-init flink-jobmanager flink-taskmanager
   docker compose ps
   docker compose logs -f postgres redis kafka kafka-init flink-jobmanager flink-taskmanager
   ```

3. Start the local/static IB Gateway compatibility service, then verify its public process health.

   ```bash
   docker compose up --build --no-deps -d ib_gateway
   curl -fsS http://localhost:8080/healthz
   docker compose logs -f ib_gateway
   ```

4. Start the Backend after the infrastructure and Gateway. Managed QCH configuration is optional locally: when it is absent, the Backend and non-IBKR features remain available, while managed session creation is disabled. `/healthz` is process liveness; `/readyz` checks required Backend/database/recommendation readiness and reports managed Gateway availability without making missing QCH configuration a global failure.

   ```bash
   docker compose up --build --no-deps -d backend
   curl -fsS http://localhost:8000/healthz
   curl -fsS http://localhost:8000/readyz
   curl -fsS http://localhost:8000/api/v1/system/
   docker compose logs -f backend
   ```

5. Start the Frontend last, then open the application.

   ```bash
   docker compose up --build --no-deps -d frontend
   curl -fsS http://localhost:5173/healthz
   docker compose logs -f frontend
   ```

   The application is at <http://localhost:5173>. Existing sessions remain visible when managed Gateway deployment is unavailable.

To stop components individually in reverse order, use:

```bash
docker compose stop frontend
docker compose stop backend
docker compose stop ib_gateway
docker compose stop flink-taskmanager flink-jobmanager kafka redis postgres
```

To stop and remove the complete stack while preserving named volumes, use `docker compose down`. Add `-v` only when intentionally discarding all local database, Kafka, Flink, and Gateway state.

Validate the complete private Kafka/Flink topology and restart recovery with:

```powershell
powershell -NoProfile -File docs/compose_smoke.ps1
powershell -NoProfile -File docs/streaming_recovery_smoke.ps1
```

Compose's `ib_gateway` is an explicitly local/static compatibility service using the real `ib_async` adapter and `${IBC_TRADING_MODE:-paper}`. Configure its credentials in the root `.env` only when testing legacy local flows. Backend production logic has no global gateway route; managed sessions require the QCH injected variables and published `IBKR_GATEWAY_IMAGE` described in [QFS deployment](QFS_DEPLOYMENT.md). Until IBKR authentication completes, broker health stays disconnected and risk correctly blocks submissions.

The static compatibility route is enabled only by `BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED=true` in Compose. Never enable it in production. PostgreSQL and Redis are reachable only on the private Compose network and are not published to the host.

For host-side tests, use a separate Python environment per Python application because both intentionally own their dependencies. SQLite is the automatic test database.

Health URLs:

```text
GET http://localhost:5173/healthz
GET http://localhost:8000/healthz
GET http://localhost:8080/healthz
```
