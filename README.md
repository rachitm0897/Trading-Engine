# Trading Engine Frontend

This branch is the standalone React/TypeScript operator application. Vite builds the static application and production Nginx serves it below the QFS route prefix. A normal clone of this branch contains everything needed to install, test, build, and package the Frontend; it does not require any Backend or infrastructure source tree.

The browser communicates with the Backend only through the public `BACKEND_API_URL`. The Frontend has no PostgreSQL, Redis, Kafka, Flink, QCH, Gateway-image, registry, or service-token configuration.

## Local development

Use Node.js 22 or later from the repository root:

```bash
npm ci
npm run dev
```

Vite listens on all interfaces. Set `VITE_API_BASE_URL` when local browser traffic should use a different Backend API; the example defaults to `http://localhost:8000/api/v1`. `VITE_APP_BASE_PATH` defaults to `/` in development.

## Tests and production verification

```bash
npm ci
npm test
npm run test:production-build
docker build -t trading-engine-frontend .
```

`npm test` runs Vitest and React Testing Library, then verifies the deployment configuration. `npm run test:production-build` type-checks the TypeScript source, builds the Vite bundle, and verifies prefixed production assets and runtime configuration.

## QFS deployment

The production route and runtime connection are:

```text
VITE_APP_BASE_PATH=/trading_eng_frontend/
BACKEND_API_URL=https://qfsplatform.com/trading_eng_backend/api/v1
```

Build the image from the repository root:

```bash
docker build -t trading-engine-frontend .
```

At container startup, `docker-entrypoint.d/40-runtime-config.sh` validates `BACKEND_API_URL` as a single-line HTTP(S) URL and generates `runtime-config.js`. The file is served with `Cache-Control: no-store`, so the Backend URL can be changed at runtime without rebuilding the static bundle. The image contains no `.env` file and Nginx does not proxy API traffic or use private Docker DNS.

The production Vite base is `/trading_eng_frontend/`. React Router reads Vite's `BASE_URL`, keeping its basename aligned with emitted asset paths. Nginx:

- redirects the exact `/trading_eng_frontend` path to `/trading_eng_frontend/`;
- serves assets and lazy chunks below the configured prefix;
- supports both prefix-preserved and prefix-stripped QFS requests;
- falls back to `index.html` for SPA deep links; and
- exposes `GET /healthz` as plain-text liveness.

## Application routes

- `/dashboard` shows account and portfolio summaries, charts, holdings, orders, activity, and attention items.
- `/strategies`, `/strategies/new`, and `/strategies/:id` cover strategy inventory, creation, controls, configuration, and execution detail.
- `/portfolio-builder` and `/portfolio` cover construction, qualification, allocation, holdings, drift, rebalancing, and optimization.
- `/activity` shows orders, executions, operational activity, and the guarded manual ticket.
- `/ibkr-sessions` operates managed broker sessions and Backend-proxied noVNC links.
- `/system` reports Gateway, streaming, reconciliation, provider, risk, and audit status.

All server data remains owned by TanStack Query; local Zustand stores hold only UI and selection preferences. The application never connects directly to IBKR/TWS and does not fabricate market, portfolio, or execution values. See `docs/FRONTEND_REDESIGN.md` for the operator workflow and current visualization limits.
