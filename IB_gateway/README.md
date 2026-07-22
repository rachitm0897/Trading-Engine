# Private IB Gateway child image

This directory builds the reusable Docker Hub image that QCH starts once per managed IBKR session. It is not a QFS website application and is not part of the normal Compose stack.

The image contains IB Gateway, IBC, Xvfb, Fluxbox, x11vnc, noVNC/websockify, Django/Gunicorn, Nginx, Supervisor, the broker worker, and Tini. It exposes only port `8080`; TWS (`4001`/`4002`), VNC (`5900`), websockify (`6080`), and Gunicorn (`8001`) are private listeners.

The IBKR installer is x86-64 only. Build with `linux/amd64`:

```bash
cd IB_gateway
docker buildx build \
  --platform linux/amd64 \
  --load \
  -t <DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version> \
  .
docker push <DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
```

Optional OCI metadata uses `OCI_VERSION`, `OCI_REVISION`, and `OCI_CREATED` build arguments. Never put credentials in build arguments or labels.

After publication, resolve the immutable Docker Hub digest and configure it only on the Backend:

```bash
docker pull docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
docker image inspect --format='{{index .RepoDigests 0}}' docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
```

```text
IBKR_GATEWAY_IMAGE=docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway@sha256:<digest>
```

QCH performs the pull. The Backend only sends the validated image reference and never handles registry credentials.

## Child contract

Nginx on port `8080` exposes only:

- public `GET /healthz`
- authenticated `/api/v1/*`
- `/novnc/*`

There is no public-path prefix mode. The Backend connects to `http://<child-container-name>:8080/api/v1`, and managed noVNC remains publicly reachable only through the Backend proxy.

The Backend supplies this per-session environment:

```text
DJANGO_SECRET_KEY=<unique ephemeral secret>
GATEWAY_SERVICE_TOKEN=<unique session token>
NOVNC_PASSWORD=<unique session password>
IB_USERNAME=<session username>
IB_PASSWORD=<session password>
IBC_TRADING_MODE=paper|live
BROKER_ADAPTER=ib_async
PORT=8080
```

Real-mode startup validates required values before creating runtime files or applying migrations. Missing values, placeholders, line breaks, invalid modes, and invalid numeric tuning fail closed without echoing secrets. Temporary IBKR credentials are written only to the mode-0600 runtime IBC configuration and removed from the process environment after configuration.

Low-level optional defaults are `IBKR_CLIENT_ID=17`, `TWS_MAJOR_VRSN=1045`, `IBC_2FA_TIMEOUT=180`, `IBC_AUTO_RESTART_TIME=11:45 PM`, `BROKER_REFRESH_SECONDS=5`, `GATEWAY_DB_PATH=/data/gateway.sqlite3`, seven-day event/health retention, hourly compaction, and a 1000-row compaction batch. QCH currently attaches no persistent volume, so managed child state is disposable.

## Local image validation

Local `docker run` is an image-validation procedure only. Mock mode needs no IBKR account:

```bash
docker run --rm --name ib-gateway-mock \
  -p 127.0.0.1:8080:8080 \
  -e BROKER_ADAPTER=mock \
  -e DJANGO_SECRET_KEY=mock-only-django-secret-for-local-smoke \
  -e GATEWAY_SERVICE_TOKEN=mock-only-service-token-for-local-smoke \
  -e NOVNC_PASSWORD=mockvnc1 \
  trading-engine-ib-gateway:local
```

Validate public health and authenticated API behavior:

```bash
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/api/v1/health/
curl -i -H 'Authorization: Bearer mock-only-service-token-for-local-smoke' http://127.0.0.1:8080/api/v1/health/
```

The expected statuses are `200`, `401`, and `200`. For a real local validation, place credentials in an owner-restricted environment file outside the repository and use `docker run --env-file`; never type or commit them.

## Tests

```bash
pytest
```

Tests use explicit mock credentials and do not require an IBKR account. Historical market-data and schedule routes remain authenticated, bounded, durable read-only commands.
