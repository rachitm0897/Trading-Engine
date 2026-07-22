# Local development

Docker Compose is only a local stack for PostgreSQL, Redis, Kafka, topic initialization, Flink, Backend, and Frontend. It does not start an IBKR Gateway container.

1. Optionally copy the small root example and replace local-only secrets:

   ```bash
   cp .env.example .env
   ```

   The ignored `.env` remains outside every production image.

2. Start infrastructure:

   ```bash
   docker compose up -d postgres redis kafka kafka-init flink-jobmanager flink-taskmanager
   docker compose ps
   docker compose logs -f postgres redis kafka kafka-init flink-jobmanager flink-taskmanager
   ```

3. Start the Backend:

   ```bash
   docker compose up --build --no-deps -d backend
   curl -fsS http://localhost:8000/healthz
   curl -fsS http://localhost:8000/readyz
   curl -fsS http://localhost:8000/api/v1/system/
   ```

   QCH and `IBKR_GATEWAY_IMAGE` are intentionally absent by default. Managed broker-session creation is unavailable, but health, research, portfolio, streaming, and all other non-broker features continue to start normally. Every broker operation still requires a real managed session; there is no static local route.

4. Start the Frontend:

   ```bash
   docker compose up --build --no-deps -d frontend
   curl -fsS http://localhost:5173/healthz
   ```

   Open <http://localhost:5173>. Runtime configuration points the browser to `http://localhost:8000/api/v1`; Nginx does not proxy `/api/v1`.

Stop individual components in reverse order:

```bash
docker compose stop frontend backend
docker compose stop flink-taskmanager flink-jobmanager kafka redis postgres
```

`docker compose down` removes containers and the network while preserving named data volumes. Add `-v` only when intentionally discarding local PostgreSQL, Kafka, and Flink state.

Run the local topology smoke checks with:

```powershell
powershell -NoProfile -File docs/compose_smoke.ps1
powershell -NoProfile -File docs/streaming_recovery_smoke.ps1
```

The Compose smoke verifies seven long-running services, Backend and Frontend health, SPA deep links, the absolute runtime Backend URL, absent demo accounts, disabled managed-session creation without QCH, and private Kafka/Flink listeners.

For host-side Python tests, use a separate environment per Python application because the Backend and child image own different dependencies. Tests default to SQLite when `DATABASE_URL` is unset; if a local component `.env` points to external PostgreSQL, explicitly set `DATABASE_URL=sqlite:///:memory:` for an isolated test run.

Local health URLs:

```text
GET http://localhost:5173/healthz
GET http://localhost:8000/healthz
```

`docker run` for the image under `IB_gateway/` is a separate image-validation procedure documented in that directory. It is not part of the Compose application topology.
