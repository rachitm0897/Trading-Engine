# Trading Engine Infrastructure

This branch is the standalone infrastructure stack and private IB Gateway image source. It is not an all-in-one application image and it is not a public QFS website.

The Compose stack contains only PostgreSQL, Redis, Kafka, Kafka topic initialization, Flink JobManager, and Flink TaskManager. Application deployments consume these services through their own environment variables; no application source or application credentials are present here.

## Compose stack

Validate and start the stack from the repository root:

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
```

The `private` Compose network carries service-to-service traffic. PostgreSQL is published on `${POSTGRES_PORT:-5433}` for controlled local access. Redis, Kafka, and Flink do not publish host listeners. Production consumers should use secured externally reachable endpoints or an explicitly managed shared network rather than relying on sibling source checkouts.

Compose owns these named volumes:

- `postgres_data` for PostgreSQL data;
- `kafka_data` for Kafka logs;
- `flink_checkpoints` for Flink checkpoints; and
- `flink_savepoints` for Flink savepoints.

`docker compose down` removes containers and the project network but preserves the named volumes. Add `-v` only when intentionally discarding all local infrastructure state.

## Kafka topics

After Kafka passes its health check, the one-shot `kafka-init` service mounts `streaming/kafka/create-topics.sh` and creates the contracts declared in `streaming/kafka/topics.yml`. Schemas live under `streaming/kafka/schemas/`. Kafka is durable transport; PostgreSQL remains the authoritative store for financial facts.

## Flink

Both Flink services build `streaming/flink/Dockerfile`. The JobManager waits for topic initialization and automatically submits the versioned Python jobs. JobManager and TaskManager share checkpoint and savepoint volumes, use stable job/operator identities, and communicate with Kafka through the Compose network.

Build the Flink image independently with:

```bash
docker build -t trading-engine-flink ./streaming/flink
```

The streaming recovery smoke test restarts both Flink roles and verifies that all expected jobs recover:

```powershell
powershell -NoProfile -File docs/streaming_recovery_smoke.ps1
```

## Private IB Gateway image

`IB_gateway/` is image source only. The managed Gateway is not a permanent Compose service and exposes no public QFS route. Build the child image for its required architecture:

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  -t trading-engine-ib-gateway:local \
  ./IB_gateway
```

The image exposes port `8080` with public `/healthz`, authenticated `/api/v1/*`, and `/novnc/*`. It contains IB Gateway, IBC, noVNC, and its private HTTP service; it has no application-source dependency.

For Docker Hub publication, use an immutable version tag, push it, and resolve the repository digest:

```bash
docker tag trading-engine-ib-gateway:local <dockerhub-user>/trading-engine-ib-gateway:<version>
docker push <dockerhub-user>/trading-engine-ib-gateway:<version>
docker image inspect --format='{{index .RepoDigests 0}}' <dockerhub-user>/trading-engine-ib-gateway:<version>
```

QCH, not Compose and not application-side Docker code, pulls that image and creates one private child container per managed broker session. Backend deployments consume only the resulting immutable reference:

```text
docker.io/<dockerhub-user>/trading-engine-ib-gateway@sha256:<digest>
```

Registry authentication belongs on the QCH host. Do not store registry credentials, brokerage credentials, QCH application credentials, or child service tokens in this branch.

## Tests and builds

```bash
docker compose config --quiet
pip install -r IB_gateway/requirements.txt
python -m pytest -q IB_gateway/tests
pip install -r streaming/flink/requirements.txt
python -m pytest -q streaming/flink/tests
docker build --platform linux/amd64 -t trading-engine-gateway ./IB_gateway
docker build -t trading-engine-flink ./streaming/flink
```

Run `docs/compose_smoke.ps1` for a local infrastructure-only startup check. See `IB_gateway/README.md` and `streaming/README.md` for component contracts.
