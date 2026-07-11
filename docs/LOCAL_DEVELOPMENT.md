# Local development

1. Copy `.env.example` to `.env`; replace local tokens and passwords.
2. Run `docker compose up --build -d`.
3. Wait for `docker compose ps` to show all services healthy.
4. Inspect logs with `docker compose logs -f backend ib_gateway frontend`.
5. Stop with `docker compose down`. Add `-v` only when intentionally discarding all local database and Gateway state.

The local Gateway uses its mocked broker adapter. This exercises the REST command/event contract without credentials. PostgreSQL and Redis are reachable only on the private Compose network and are not published to the host.

For host-side tests, use a separate Python environment per Python application because both intentionally own their dependencies. SQLite is the automatic test database.

Health checks:

```text
GET http://localhost:5173/healthz
GET http://localhost:8000/healthz
GET http://localhost:8080/healthz
```

