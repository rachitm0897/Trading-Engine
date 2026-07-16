# Finflock terminal frontend

The React/TypeScript operator application is a dark, information-dense trading terminal organized around operator workflows. It displays only Backend API data: the browser never connects directly to IBKR/TWS and does not synthesize market or portfolio values.

## Routes

- `/dashboard` — selected account and portfolio summary, real NAV/P&L and exposure charts, holdings, open orders, activity, and attention items.
- `/strategies` — filterable strategy inventory with safe enable, pause, flatten, and delete controls.
- `/strategies/new` — schema-driven strategy wizard; defaults to `SHADOW` and does not expose `LIVE`.
- `/strategies/:id` — strategy overview, price/indicator chart, execution activity, configuration, versions, and inputs.
- `/portfolio-builder` — goal construction, instrument qualification, strategy assignment, combined preview, and guarded apply workflow.
- `/portfolio` — holdings, cash, allocation, concentration, drift, and advanced flow/rebalance/optimization tools.
- `/activity` — order blotter, responsive order inspector, executions, operational activity, and advanced manual ticket.
- `/system` — Gateway/noVNC, streaming, reconciliation, provider status, risk/kill switch, and audit controls.

All feature routes are lazy-loaded while the terminal shell remains mounted.

## Terminal shell and preferences

The desktop sidebar has expanded and compact modes. Below the mobile breakpoint it becomes an independent navigation drawer, so opening the drawer never changes the saved desktop mode. The top bar preserves global account and portfolio selection, health/freshness status, and the real-data ticker.

Workspace preferences are persisted by `src/stores/workspacePreferences.ts` under `finflock-workspace-v1`. They include sidebar mode, density, panel collapse state, right-rail preference, and per-chart controls. Mobile-drawer and fullscreen state are deliberately session-only. Invalid persisted values fall back to safe defaults.

`src/stores/preferences.ts` and `src/stores/useSelection.ts` contain local selection preferences only. TanStack Query remains the owner of every server value, polling lifecycle, stale/error state, retry, and mutation invalidation; Zustand is not used as a server-data cache.

## Panels and charts

`TerminalPanel` is the single normal information-panel primitive. A route-scoped `id` gives each panel persisted collapse state. Collapsing uses the HTML `hidden` state rather than unmounting content, preserving form and query component state. Panels expose accessible keyboard toggles and can opt into fullscreen mode, which exits with Escape.

`TerminalChart` keeps one Lightweight Charts instance for its lifetime and updates retained series as API data changes. Depending on available data it supports candlesticks, line/area views, volume, indicators, execution markers, crosshair legends, percentage scale, ranges, intervals, fit/reset, auto-scroll, and fullscreen. Chart input is sorted, deduplicated, bounded, and validated; empty or invalid API data produces an explicit empty state rather than a fabricated series.

Theme and chart colors come from the semantic variables in `src/styles/tokens.css`.

## Safety and data flow

Strategies still emit signals and targets. Executable actions continue through allocation, sizing, pre-trade risk, OMS, Gateway, append-only ledgers, and reconciliation. Existing confirmation, reason, eligibility, paper/shadow, kill-switch, and idempotency controls are unchanged by the presentation layer.

The current redesign required no Backend changes. Existing chart endpoints may accept optional `range` and `interval` query parameters; omitting them preserves the established response and query-cache contracts.

## Development

Use Node.js and run from this directory:

```bash
npm install
npm run dev
npm test
npm run build
```

`npm test` runs Vitest and React Testing Library coverage for routes, workflows, responsive shell state, persisted panels, chart normalization, and safety controls. `npm run build` runs TypeScript project compilation before creating the Vite production bundle.

Set `VITE_API_BASE_URL` to the public Backend `/api/v1` URL and `VITE_APP_BASE_PATH` to `/` locally or `/trading_eng_frontend/` on QFS. `VITE_GATEWAY_PUBLIC_URL` is used only for the noVNC operator link. Health remains `GET /healthz` when served by Nginx.
