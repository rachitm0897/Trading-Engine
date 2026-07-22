# IB Gateway image

This directory builds the reusable, registry-neutral image used for one isolated IBKR session. The image contains IB Gateway, IBC, Xvfb, Fluxbox, x11vnc, noVNC/websockify, Django/Gunicorn, Nginx, Supervisor, the broker worker, and Tini as PID 1. Only Nginx port `8080` is exposed; TWS (`4001`/`4002`), VNC (`5900`), websockify (`6080`), and Gunicorn (`8001`) stay on loopback.

The Interactive Brokers installer is Linux x86-64 only. Production builds must target `linux/amd64`; ARM64 is not supported or claimed.

## Build and publish manually to Docker Hub

From this directory:

```bash
cd IB_gateway

docker buildx build \
  --platform linux/amd64 \
  --load \
  -t <DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version> \
  .
```

Optional OCI metadata can be supplied with `--build-arg OCI_VERSION=...`, `OCI_REVISION=...`, and `OCI_CREATED=...`. The default command above remains valid without them. Build arguments and labels must never contain secrets.

Log in and push only when performing the separate manual publication step:

```bash
docker login
docker push <DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
```

After the push, pull the registry result and inspect its immutable repository digest:

```bash
docker pull docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
docker image inspect \
  --format='{{index .RepoDigests 0}}' \
  docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway:<version>
```

Configure production with the returned digest:

```text
IBKR_GATEWAY_IMAGE=docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway@sha256:<digest>
```

A fixed version tag is supported during development:

```text
IBKR_GATEWAY_IMAGE=docker.io/<DOCKERHUB_USERNAME>/trading-engine-ib-gateway:v1.0.0
```

Do not use `latest` in production. The Docker Hub repository must initially be public because the current QCH create-container API has no registry-credential field.

## Runtime contract

The image defaults to `PORT=8080`, an empty `APP_BASE_PATH`, and `BROKER_ADAPTER=ib_async`. An explicit safe prefix such as `/trading_eng_gateway` remains supported. `GET /healthz` is public; every `/api/v1/*` route requires `Authorization: Bearer <GATEWAY_SERVICE_TOKEN>`. Existing API paths are unchanged.

For each managed session the Backend creates a unique child name, generates a unique ephemeral `DJANGO_SECRET_KEY`, and sends QCH:

```text
DJANGO_SECRET_KEY
GATEWAY_SERVICE_TOKEN
NOVNC_PASSWORD
IB_USERNAME
IB_PASSWORD
IBC_TRADING_MODE=paper|live
BROKER_ADAPTER=ib_async
PORT=8080
APP_BASE_PATH=
```

QCH also receives the configured image reference and `QCH_SUBCONTAINER_NETWORK`. The Backend then connects to `http://<container-name>:8080/api/v1`. The Django secret exists only in the QCH request and child environment; it is not stored on the broker-session model.

Real `ib_async` startup fails before migrations or process startup if a required value is missing, empty, or a known placeholder. `paper` maps to TWS port `4002`; `live` maps to `4001`. `IBC_2FA_TIMEOUT` and `IBC_AUTO_RESTART_TIME` preserve IBC two-factor and scheduled-restart behavior. Credentials are written atomically only to the runtime IBC configuration with mode `0600` and ownership by `ibgateway`.

## Local mock smoke test

Mock mode requires no IBKR account, but security values remain explicit:

```bash
docker run --rm --name ib-gateway-mock \
  -p 127.0.0.1:8080:8080 \
  -e BROKER_ADAPTER=mock \
  -e DJANGO_SECRET_KEY=mock-only-django-secret-for-local-smoke \
  -e GATEWAY_SERVICE_TOKEN=mock-only-service-token-for-local-smoke \
  -e NOVNC_PASSWORD=mockvnc1 \
  trading-engine-ib-gateway:local
```

In another shell:

```bash
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/api/v1/health/
curl -i \
  -H 'Authorization: Bearer mock-only-service-token-for-local-smoke' \
  http://127.0.0.1:8080/api/v1/health/
```

The first request must return `200`, the unauthenticated protected request must return `401`, and the authenticated request must return `200`. Mock mode keeps Django, Nginx, Supervisor, health, noVNC, and the mock broker worker testable without starting IB Gateway/IBC.

## Local real-session testing

Never type real credentials directly into a command where shell history or process inspection can retain them. Create an environment file outside the repository, restrict it to its owner (for example `chmod 600 /secure/path/ib-gateway.env`), and supply it with `docker run --env-file /secure/path/ib-gateway.env ...`. Required names are:

```text
BROKER_ADAPTER=ib_async
DJANGO_SECRET_KEY=<unique-random-secret>
GATEWAY_SERVICE_TOKEN=<unique-random-token>
NOVNC_PASSWORD=<unique-password>
IB_USERNAME=<ibkr-username>
IB_PASSWORD=<ibkr-password>
IBC_TRADING_MODE=paper
PORT=8080
APP_BASE_PATH=
```

Use `IBC_TRADING_MODE=live` only when intentionally connecting a live account. Never commit the environment file. Persisting `/data` or `/home/ibgateway/Jts` is optional for standalone use; the current QCH child API does not mount volumes, so managed child state is disposable.

## Tests

```bash
pytest
```

Tests use explicit test-only Django and service-token values and never require a real IBKR account.

## Bounded research history

`POST /api/v1/market-data/history/` remains an authenticated, durable, read-only broker command. It requires an exact positive conId and supports `1 min`, `5 mins`, `15 mins`, `1 hour`, and `1 day` bars with `TRADES` or `ADJUSTED_LAST`. Intraday duration is bounded to 90 days and daily duration to ten years.

`POST /api/v1/market-data/schedule/` returns up to 365 days of exact-contract historical trading sessions. Both paths remain idempotent durable commands and do not open an order path or live subscription.
