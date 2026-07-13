# Finflock frontend

The React/TypeScript operator application is organized around the trading workflow rather than infrastructure modules.

## Routes

- `/dashboard` — selected account/portfolio summary, operating state, real NAV/P&L and exposure charts, activity, and attention items.
- `/strategies` — searchable strategy instances with safe enable, pause, and flatten controls.
- `/strategies/new` — five-step schema-driven strategy wizard; defaults to `SHADOW` and never exposes `LIVE`.
- `/strategies/:id` — overview, chart, activity, configuration, and advanced version/input tabs.
- `/portfolio` — holdings, cash, allocation, concentration, drift, and advanced flow/rebalance/sizing tools.
- `/activity` — combined orders, fills, normal activity, order details, and the advanced manual ticket.
- `/system` — Gateway/noVNC, Streaming, Reconciliation, Risk/kill switch, and Audit accordions.

## Architecture

TanStack Query owns Backend state, polling, stale state, retries, mutation invalidation, and route-specific fetching. Zustand owns only the selected account/portfolio and responsive navigation preference. Typed API contracts live in `src/api`, feature routes in `src/features`, shared primitives in `src/components`, and theme/responsive styles in `src/styles`.

The frontend talks only to Backend APIs. Strategies emit signals and targets; executable actions continue through allocation, sizing, risk, OMS, Gateway, ledgers, and reconciliation. There is no browser-to-IBKR or browser-to-TWS path.

## Development

```bash
npm install
npm run dev
npm test
npm run build
```

Set `VITE_API_BASE_URL` to the public Backend `/api/v1` URL and `VITE_APP_BASE_PATH` to `/` locally or `/trading_eng_frontend/` on QFS. `VITE_GATEWAY_PUBLIC_URL` is used only for the noVNC operator link. Health remains `GET /healthz` when served by Nginx.

