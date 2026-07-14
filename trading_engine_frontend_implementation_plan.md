# Trading Engine Frontend-First Implementation Plan

## 1. Product Goal

Turn the current operations terminal into a clean trading-engine control application where a user can:

1. Select a portfolio and broker account.
2. Choose or enter a ticker.
3. Choose a strategy definition.
4. Configure strategy parameters, timeframe, capital allocation, risk policy, and order policy.
5. Validate the configuration.
6. Start it in `SHADOW`, `OBSERVE`, or `PAPER` mode.
7. Monitor the path from market data to signal, target, order intent, order, fill, position, and reconciliation.
8. Intervene safely through pause, flatten, cancel, and kill-switch controls.

The default interface must show only the information needed for normal operation. Detailed stream, allocation, risk, broker, and audit information belongs in drawers, tabs, and collapsible advanced sections.

## 2. Repository Audit

### What is already strong

- Backend domain boundaries follow the intended architecture: strategy targets, allocation, risk and sizing, OMS, broker gateway, execution ledger, and reconciliation are separated.
- Strategy definitions and instances are data-backed and already support configurable ticker, timeframe, parameters, target configuration, risk policy, order policy, and execution mode.
- The backend exposes strategy state, runs, signals, targets, versions, requirements, and execution timeline.
- Kafka, Flink, PostgreSQL outbox processing, IBKR Gateway isolation, paper-first execution, and idempotency controls are present.
- The current repository documents passing backend, gateway, streaming, and frontend tests.

### Main frontend problems

1. **One-file application:** most screens and business UI are contained in `Frontend/src/App.tsx`.
2. **Architecture-driven navigation:** thirteen equally visible pages expose internal services instead of the operator workflow.
3. **Global polling:** the Zustand store requests about twenty endpoints every 15 seconds, whether the current page needs them or not.
4. **Weak typing:** server data is stored as `any`, making modifications risky.
5. **Generic table rendering:** nested parameters and indicators are JSON-stringified into cells instead of being presented meaningfully.
6. **Hardcoded chart:** the portfolio chart uses fixed sample values rather than backend data.
7. **Fixed selection assumptions:** some actions use the first account or portfolio instead of an explicit user selection.
8. **No real routing:** `react-router-dom` is installed but navigation is local component state, so pages are not bookmarkable.
9. **Poor responsiveness:** the CSS enforces a minimum width of 1120 px and treats nearly every surface as a bordered panel.
10. **No progressive disclosure:** routine and advanced controls are shown together.
11. **Limited UX states:** loading, partial failure, empty state, stale data, last refresh, and retry handling are weak.
12. **Insufficient frontend tests:** existing tests mainly confirm that pages and a few controls render.

### Important platform gaps outside the first frontend phase

- Authentication and authorization are not implemented for a production trading platform.
- Several backend views are CSRF-exempt and have no user-level permission checks.
- PostgreSQL is published to the host in Compose even though the architecture describes private data infrastructure.
- The Compose stack uses PostgreSQL rather than a TimescaleDB image for time-series storage.
- Server-side filtering and pagination are limited for orders, executions, logs, and strategy histories.
- High-availability broker connector election and full live-trading certification remain incomplete.

These gaps should be documented and not disguised by a polished interface. A shiny button remains a button, not a risk control.

## 3. Recommended Information Architecture

Reduce primary navigation to five sections.

### 3.1 Dashboard

Purpose: answer "Is the engine healthy, what is running, and does anything need attention?"

Show:

- selected account and portfolio;
- `PAPER` or `SHADOW` operating badge;
- IBKR connection and reconciliation status;
- NAV, cash, buying power, daily P&L, exposure, and open-order count;
- portfolio NAV/P&L chart using real data;
- active strategy summary;
- recent signal-to-fill activity timeline;
- unresolved alerts, risk blocks, stale prices, and reconciliation breaks;
- primary action: **Create Strategy**.

Hide Gateway, Kafka, Flink, and raw audit details behind a compact system-health drawer.

### 3.2 Strategies

#### Strategy list

Show one row or card per strategy instance:

- name;
- ticker;
- strategy type;
- timeframe;
- execution mode;
- state;
- warm-up progress;
- latest signal;
- current target;
- attributed quantity;
- active order;
- last update;
- actions: view, enable, pause, flatten.

Include search and filters for portfolio, ticker, strategy type, mode, and state.

#### Create Strategy wizard

Use a guided five-step flow:

1. **Instrument:** ticker, exchange, currency, contract qualification state.
2. **Strategy:** definition and timeframe.
3. **Parameters:** dynamically render fields from the backend parameter schema.
4. **Capital and risk:** target weight, capital share, priority, risk policy, order policy, execution mode.
5. **Review:** display a readable summary, input requirements, warm-up bars, and validation result.

Defaults:

- execution mode: `SHADOW`;
- advanced fields collapsed;
- no `LIVE` option;
- ticker is never hardcoded;
- strategy definitions are loaded from the backend.

#### Strategy detail

Use tabs:

- **Overview:** state, target, position, P&L, risk, active order.
- **Chart:** price or bars with indicator overlays and markers for signals, targets, orders, and fills.
- **Activity:** execution timeline from run to fill.
- **Configuration:** current version and readable parameter groups.
- **Advanced:** versions, input bindings, raw identifiers, and technical metadata.

### 3.3 Portfolio

Show:

- account and portfolio selector;
- positions and cash;
- allocation by instrument and strategy;
- gross/net exposure;
- concentration and sector exposure where metadata exists;
- drift from target;
- recent P&L/NAV history;
- rebalance preview and flow-allocation actions.

Put single-stock sizing, cost assumptions, turnover controls, and raw allocation decisions in collapsible advanced sections.

### 3.4 Orders & Activity

Combine Orders, Executions, and normal operational history.

Provide:

- filterable order blotter;
- tabs for active, completed, rejected, and all orders;
- side, type, quantity, fill progress, average fill price, status, and update time;
- order detail drawer with intent, risk decision, broker IDs, status history, attribution, and fills;
- cancel and modify actions only when valid;
- execution list;
- combined activity timeline.

The manual order ticket should be an advanced operator action, not the central experience.

### 3.5 System

Consolidate Gateway, Streaming, Reconciliation, Risk, and Audit into one operational page.

Use accordion sections:

- IBKR Gateway and noVNC;
- reconciliation and unresolved breaks;
- kill switches and risk decisions;
- Kafka, Flink, outbox, dead-letter, stale-price metrics;
- audit log;
- environment and deployment information.

Dangerous actions require explicit confirmation and a typed reason.

## 4. Frontend Architecture

Recommended structure:

```text
Frontend/src/
  app/
    App.tsx
    router.tsx
    providers.tsx
  layouts/
    AppShell.tsx
  routes/
    DashboardPage.tsx
    StrategiesPage.tsx
    StrategyCreatePage.tsx
    StrategyDetailPage.tsx
    PortfolioPage.tsx
    OrdersPage.tsx
    SystemPage.tsx
  features/
    dashboard/
    strategies/
    portfolio/
    orders/
    system/
  components/
    ui/
    charts/
    tables/
    feedback/
  api/
    client.ts
    queries.ts
    mutations.ts
    types.ts
  stores/
    preferences.ts
  styles/
    tokens.css
    globals.css
```

### State management

- Use TanStack Query for backend/server state, caching, polling, retries, and invalidation.
- Keep Zustand only for user-interface preferences such as selected portfolio, sidebar state, saved filters, table density, and collapsed sections.
- Fetch only data required by the active route.
- Poll health and active-order data more frequently than static definitions and policies.
- Display last-updated time and stale state.

### Type safety

- Define TypeScript interfaces for every API response used by the frontend.
- Avoid `any` in new code.
- Keep the existing response envelope.
- Add runtime validation only where external or unstable payloads justify it.

### Reusable UI components

Build a small internal component system rather than importing a giant dashboard kit:

- `StatusBadge`
- `MetricCard`
- `PageHeader`
- `CollapsibleSection`
- `DetailDrawer`
- `DataTable`
- `FilterBar`
- `EmptyState`
- `ErrorState`
- `Skeleton`
- `ConfirmActionDialog`
- `TimeSeriesChart`
- `ActivityTimeline`
- `ProgressBar`

## 5. Visual Design Rules

- Keep a dark professional theme, but remove the terminal-style all-caps treatment from normal text.
- Use monospace only for IDs, ticker symbols, quantities, prices, and logs.
- Use semantic colors only for status and risk.
- Prefer spacing and typography over borders around every block.
- Use one main content column with optional secondary context panels.
- Use drawers and accordions for technical details.
- Support desktop and tablet widths; remove the global `min-width: 1120px`.
- Keep the left navigation collapsible.
- Provide a consistent 8 px spacing system and clear heading hierarchy.
- Include keyboard focus states and accessible labels.

## 6. Interactive Visuals

### Required in the first redesign

1. Portfolio NAV or P&L line chart with range selection.
2. Exposure or allocation bar visualization.
3. Strategy price chart with signal, target, order, and fill markers.
4. Warm-up progress indicator.
5. Order fill-progress indicator.
6. Signal-to-fill activity timeline.
7. Health indicators for broker, reconciliation, market-data freshness, Kafka/Flink, and risk state.

No graph should use hardcoded sample data in production code.

## 7. Backend Changes Needed for the UI

Keep backend changes additive and narrow.

### Priority API additions

1. `GET /api/v1/dashboard/summary/`
   - selected account/portfolio summary;
   - health and attention counts;
   - active strategy summary;
   - recent activity.

2. `GET /api/v1/portfolios/<id>/timeseries/`
   - NAV, cash, realized/unrealized P&L, and exposure by timestamp;
   - range and interval parameters.

3. `GET /api/v1/strategy-instances/<id>/chart/`
   - market bars;
   - relevant indicator series;
   - signals, targets, order intents, orders, and fills as markers.

4. Add query filters and pagination to:
   - orders;
   - executions;
   - audit events;
   - strategy runs/signals/targets;
   - reconciliation breaks.

5. Add portfolio and account identifiers to summary payloads consistently.

### Non-negotiable backend constraints

- Strategies still return signals and targets, never direct broker orders.
- All executable changes pass through sizing, risk, OMS, Gateway, ledger, and reconciliation.
- No frontend or strategy plugin receives TWS socket access.
- Every mutation keeps idempotency protection.
- `LIVE` remains unavailable.
- Existing API contracts remain compatible unless a versioned replacement is introduced.

## 8. Delivery Phases

### Phase 0: Baseline and safety

- Run and record current backend, gateway, streaming, and frontend tests.
- Capture current screenshots and API response examples.
- Create a dedicated frontend-redesign branch.
- Add a short design decision document.

Exit condition: clean baseline with no unexplained failures.

### Phase 1: Frontend foundation

- Split `App.tsx` into routes, layout, features, and reusable components.
- Add React Router routes.
- Add TanStack Query and per-feature API hooks.
- Add typed API models.
- Add theme tokens and responsive layout.
- Preserve current behavior while changing structure.

Exit condition: all existing functions remain reachable and tests pass.

### Phase 2: Navigation and dashboard

- Replace thirteen primary pages with five product sections.
- Add account and portfolio selection.
- Build the new dashboard using current endpoints first.
- Replace hardcoded chart data with an empty/loading state until the real endpoint exists.
- Add health and attention summary.

Exit condition: an operator can understand system status without opening technical pages.

### Phase 3: Strategy workflow

- Build strategy list and filters.
- Build the schema-driven creation wizard.
- Add contract-qualification status.
- Add readable review and validation step.
- Keep advanced capital, risk, and order settings collapsed.

Exit condition: a user can create a strategy for an arbitrary ticker using any backend-provided definition without editing frontend code.

### Phase 4: Strategy monitoring

- Build strategy detail route and tabs.
- Add chart and activity timeline.
- Add enable, pause, and flatten controls with confirmation.
- Add readable configuration/version display.

Exit condition: the complete market-data-to-fill path is visible for one strategy instance.

### Phase 5: Portfolio and orders

- Build portfolio analytics and allocation views.
- Integrate flow allocation and rebalance preview.
- Combine order blotter, executions, and activity.
- Add order detail drawer, filters, fill progress, and valid modify/cancel controls.

Exit condition: normal monitoring no longer requires switching among several technical pages.

### Phase 6: System consolidation

- Merge Gateway, Streaming, Reconciliation, Risk, and Audit into the System page.
- Use accordions and drawers.
- Preserve noVNC access.
- Strengthen confirmation for kill switches and replay operations.

Exit condition: technical controls remain available without cluttering the main workflow.

### Phase 7: Backend support and hardening

- Add time-series, chart-overlay, summary, filtering, and pagination endpoints.
- Add endpoint tests.
- Add frontend integration tests for partial failure, stale data, empty states, and mutations.
- Update deployment and frontend documentation.

Exit condition: no production chart uses mock data, and large datasets do not require loading entire tables.

## 9. Test Plan

### Frontend unit and integration tests

- route rendering and deep links;
- account and portfolio selection;
- strategy schema rendering;
- arbitrary ticker submission;
- validation and qualification-pending states;
- advanced section collapsed by default;
- shadow mode default and absence of live mode;
- enable, pause, and flatten confirmations;
- order cancel/modify eligibility;
- kill-switch confirmation and reason;
- loading, empty, stale, partial-failure, and retry states;
- chart data mapping and marker rendering;
- QFS base path behavior;
- responsive navigation.

### Backend tests

- new summary and time-series endpoints;
- filtering and pagination;
- authorization when introduced;
- idempotency on every mutation;
- no bypass of risk, OMS, and Gateway;
- no direct broker access from frontend or strategy code.

### Quality gates

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm test && npm run build
cd .. && python -m pytest streaming/flink/tests
docker compose config --quiet
```

Also run the existing Compose smoke and recovery scripts before merging.

## 10. Definition of Done

- Primary navigation has no more than five sections.
- The normal workflow is visible and ordered.
- Advanced controls are collapsed by default.
- Ticker, strategy definition, timeframe, portfolio, policies, and parameters are backend-driven.
- No fixed ticker or strategy exists in production frontend logic.
- No hardcoded production chart series remains.
- The application uses real routes and route-level data fetching.
- The frontend does not refresh all endpoints globally every 15 seconds.
- New frontend code is typed and split into maintainable feature modules.
- Existing execution safety boundaries remain intact.
- All automated tests and builds pass.
- Documentation explains the new flow and remaining production gaps.
