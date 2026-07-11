# Greenfield IBKR Trading Execution Engine
## Implementation Plan for Codex

## 1. Project Goal

Create a completely new repository containing an IBKR-integrated trading execution engine.

The project must be built from scratch. Do not modify, migrate, or refactor the existing repository:

```text
https://github.com/rachitm0897/ibkr_gateway_docker_prototype
```

That repository may be inspected only as a read-only reference for its IB Gateway, IBC, noVNC, Docker, and IBKR connection approach.

This project is an execution platform, not:

- an AI agent;
- a research platform;
- a backtesting platform;
- a news or fundamental-analysis system;
- a user authentication product.

The first release should provide deterministic strategy execution, portfolio allocation, risk checks, order management, broker integration, fills, ledgers, and reconciliation.

---

## 2. Required Repository Structure

Create the following structure in the new repository:

```text
/
├── Backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── supervisord.conf
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── README.md
│   ├── config/
│   ├── apps/
│   └── tests/
│
├── Frontend/
│   ├── Dockerfile
│   ├── nginx.conf.template
│   ├── package.json
│   ├── .env.example
│   ├── README.md
│   ├── src/
│   └── tests/
│
├── IB_gateway/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── supervisord.conf
│   ├── nginx.conf.template
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── README.md
│   ├── config/
│   ├── gateway_service/
│   ├── broker/
│   ├── ibc/
│   └── tests/
│
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── docs/
```

The folders `Backend`, `Frontend`, and `IB_gateway` must each be independently buildable and deployable.

Each application folder must contain:

- its own Dockerfile;
- its own `.env.example`;
- its own README;
- health checks;
- tests;
- no committed secrets;
- production-ready startup commands.

---

## 3. High-Level Architecture

```text
Browser
   |
   v
Frontend
   |
   | HTTPS REST / SSE
   v
Backend
   |
   | Authenticated HTTPS REST
   v
IB_gateway Django Service
   |
   | Localhost-only TWS API socket
   v
IBC Controller
   |
   v
IB Gateway
   |
   v
Interactive Brokers
```

Infrastructure:

```text
Backend -> PostgreSQL
Backend -> Redis
Backend -> Celery
Backend -> Celery Beat
```

The Frontend must communicate only with the Backend.

The Backend must communicate with IBKR only through the `IB_gateway` REST API.

No strategy, API view, Celery task, or Frontend component may connect directly to the IBKR TWS socket.

---

## 4. Three-Container Deployment Model

The three application containers are:

1. `Backend`
2. `Frontend`
3. `IB_gateway`

For local development, `docker-compose.yml` may also start:

- PostgreSQL;
- Redis.

These are infrastructure services, not application repositories.

The full local stack must start with:

```bash
docker compose up --build -d
```

Expected local URLs:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000/api/v1/
Gateway:  http://localhost:8080/api/v1/
noVNC:    http://localhost:8080/novnc/vnc.html
```

No container may mount `/var/run/docker.sock`.

The Backend must not create, stop, inspect, or manage Docker containers.

---

## 5. QFS Deployment Targets

The target public URLs are:

```text
https://qfsplatform.com/trading_eng_backend
https://qfsplatform.com/trading_eng_frontend
https://qfsplatform.com/trading_eng_gateway
```

Each QFS application exposes only one port.

Support these environment variables:

```text
PORT
APP_BASE_PATH
PUBLIC_BASE_URL
FORWARDED_ALLOW_IPS
```

Do not hard-code QFS path prefixes.

The system should work whether QFS:

- strips the public path prefix before proxying; or
- forwards the prefix to the application.

Support forwarded headers such as:

```text
X-Forwarded-Proto
X-Forwarded-Host
X-Forwarded-Prefix
```

---

## 6. IB_gateway Service

### 6.1 Purpose

`IB_gateway` is a separate Django service containing:

- IB Gateway;
- IBC Controller;
- Xvfb;
- Fluxbox;
- x11vnc;
- noVNC;
- a Django REST API;
- one dedicated IBKR broker worker;
- Nginx;
- Supervisor.

The existing IBKR prototype may be reviewed for ideas, but the new implementation must be created in this repository without changing the old repository.

### 6.2 One-Port Design

Only Nginx may listen publicly.

Nginx listens on:

```text
0.0.0.0:${PORT:-8080}
```

Public routes:

```text
/healthz
/api/v1/*
/novnc/*
/websockify/*
```

Internal listeners:

```text
127.0.0.1:8001   Django/Gunicorn
127.0.0.1:6080   noVNC/websockify
127.0.0.1:5900   VNC
127.0.0.1:4001   IBKR live TWS API
127.0.0.1:4002   IBKR paper TWS API
```

Ports `4001`, `4002`, `5900`, `6080`, and `8001` must not be published by Docker.

Do not expose a raw TWS API proxy publicly.

### 6.3 Supervisor Processes

Supervisor should run:

1. Xvfb
2. Fluxbox
3. x11vnc
4. noVNC/websockify
5. IB Gateway through IBC
6. Django through Gunicorn
7. the broker command worker
8. Nginx

### 6.4 Gateway Persistence

Use a small local SQLite database in WAL mode for:

- durable gateway commands;
- callback/event buffering;
- idempotency;
- restart recovery.

This database is not the financial source of truth.

The Backend PostgreSQL database remains the authoritative source for:

- orders;
- fills;
- portfolios;
- cash;
- positions;
- risk decisions;
- reconciliation results.

Gateway models:

```text
GatewaySession
GatewayCommand
GatewayEvent
GatewayOrderReference
GatewayHealthSnapshot
```

### 6.5 Broker Worker

The broker worker is the only process that may own the TWS connection.

Use `ib_async` behind a broker adapter interface.

Responsibilities:

- connect to IB Gateway;
- use one configured IBKR client ID;
- serialize order-ID allocation;
- qualify contracts;
- place, modify, and cancel orders;
- request accounts, positions, orders, and executions;
- store callbacks as ordered events;
- rate-limit requests;
- retry safe read operations;
- reject duplicated commands using `idempotency_key`;
- reconnect automatically;
- restore subscriptions after reconnect;
- refresh broker state after uncertain disconnections;
- block order submission until reconciliation is complete;
- never infer fills only from order-status callbacks.

### 6.6 Gateway API

Implement:

```text
GET  /api/v1/health/
GET  /api/v1/session/
POST /api/v1/session/reconnect/

GET  /api/v1/accounts/
GET  /api/v1/account-summary/
GET  /api/v1/positions/
GET  /api/v1/open-orders/
GET  /api/v1/executions/

POST /api/v1/contracts/qualify/

POST /api/v1/orders/
PATCH /api/v1/orders/{internal_id}/
POST /api/v1/orders/{internal_id}/cancel/

GET  /api/v1/events/?after=<sequence>
POST /api/v1/events/ack/

POST /api/v1/kill-switch/
```

Protect all Backend-to-Gateway API routes using either:

- a shared service token; or
- HMAC request signing.

### 6.7 Credentials

IBKR credentials must be provided only through QFS secrets or environment variables:

```text
IB_USERNAME
IB_PASSWORD
IBC_TRADING_MODE
```

The Gateway must never:

- return credentials through APIs;
- save credentials in its database;
- log credentials;
- expose credentials to the Frontend;
- commit credentials.

Protect noVNC with a password or equivalent access control.

---

## 7. Backend Service

### 7.1 Technology

Use:

- Python 3.12;
- Django;
- Django REST Framework;
- PostgreSQL;
- Redis;
- Celery;
- Celery Beat;
- Gunicorn;
- Supervisor.

Because QFS will run only one Backend application container, Supervisor should run:

1. Gunicorn;
2. Celery worker;
3. Celery Beat.

The code must remain modular so these processes can be separated later.

### 7.2 Django Applications

Create:

```text
core
instruments
broker_gateway
accounts
portfolios
strategies
allocation
risk
oms
execution
reconciliation
audit
```

### 7.3 Core Models

Implement:

```text
Instrument
BrokerContract
BrokerAccount

TradingPortfolio
PortfolioPosition
CashLedgerEntry
PositionLedgerEntry

TradingStrategy
StrategyRun
StrategyTarget
StrategyAllocation

RebalanceRun
TargetPortfolioPosition

OrderIntent
RiskCheckResult

Order
OrderStatusHistory
Fill

ReconciliationRun
ReconciliationBreak

AuditEvent
OutboxEvent
```

### 7.4 Data Rules

- Use PostgreSQL as the transactional source of truth.
- Use `Decimal` for prices, money, quantities, P&L, and fees.
- Use append-only ledgers.
- Do not directly overwrite historical fills, cash entries, or position movements.
- Use compensating entries for corrections.
- Use database transactions and row locks.
- Add `idempotency_key` to all externally retried commands.
- Persist material events through a transactional outbox.
- Make every event consumer idempotent.
- Store all order-state changes in `OrderStatusHistory`.
- Store broker IDs separately from internal IDs.

---

## 8. Trading Pipeline

The required deterministic pipeline is:

```text
StrategyRun
  -> StrategyTarget
  -> Strategy allocation
  -> Portfolio target aggregation
  -> Rebalance calculation
  -> OrderIntent
  -> Risk checks
  -> Position sizing
  -> OMS Order
  -> Gateway command
  -> IBKR execution
  -> Gateway events
  -> Fill
  -> Cash and position ledgers
  -> Reconciliation
```

Strategies must produce desired target positions.

Strategies must never create broker orders directly.

---

## 9. Five Fixed Strategies

Implement exactly five deterministic strategy plugins.

### 9.1 Fixed-Weight Rebalance

Maintains configured target weights.

Triggers:

- schedule;
- instrument drift;
- portfolio drift;
- manual run.

### 9.2 SMA Trend

Long or flat depending on a fast and slow simple moving-average crossover.

Configuration:

```text
fast_window
slow_window
target_weight
```

### 9.3 RSI Mean Reversion

Enters when RSI is below a configured level and exits when it rises above another level.

Configuration:

```text
rsi_window
entry_threshold
exit_threshold
target_weight
```

### 9.4 Donchian Breakout

Enters on an upper-channel breakout and exits on a lower-channel breakout.

Configuration:

```text
entry_window
exit_window
target_weight
```

### 9.5 Volatility-Target Momentum

Uses signed momentum and scales exposure toward a target volatility.

Configuration:

```text
momentum_window
volatility_window
target_volatility
maximum_weight
```

Each strategy must support:

- versioned configuration;
- enabled or paused state;
- configured universe;
- schedule;
- allocated capital;
- maximum target weight;
- reproducible strategy runs;
- deterministic target generation;
- manual execution;
- no direct broker connection.

Historical bars may initially be obtained from IBKR and stored in PostgreSQL.

Do not build a separate research or backtesting framework.

---

## 10. Allocation and Rebalancing

Aggregate strategy targets before creating orders.

For each instrument:

```text
target exposure
current exposure
trade delta
lot-size rounding
minimum-notional filtering
risk-adjusted approved quantity
```

Required rebalance triggers:

- scheduled rebalance;
- instrument drift threshold;
- portfolio drift threshold;
- deposit or withdrawal;
- manual rebalance;
- strategy target change.

Suppress trades below configured:

- minimum notional;
- minimum quantity;
- minimum drift.

Reserve:

- estimated commissions;
- cash buffer;
- margin buffer.

---

## 11. Risk Controls

Implement these checks before an order can enter the OMS:

### Instrument Checks

- tradable contract;
- correct exchange and currency;
- market session;
- fresh price;
- minimum tick;
- lot size;
- short availability where required.

### Order Checks

- maximum quantity;
- maximum notional;
- limit-price collars;
- duplicate-order detection;
- pacing and rate limits.

### Strategy Checks

- allocation limit;
- maximum position weight;
- turnover limit;
- daily strategy loss;
- enabled or paused state;
- strategy freshness.

### Portfolio Checks

- available cash;
- buying power;
- maximum gross exposure;
- maximum net exposure;
- instrument concentration;
- sector concentration where data exists;
- leverage limit;
- portfolio daily-loss limit.

### Platform Checks

- Gateway connected;
- broker state reconciled;
- no unresolved material reconciliation breaks;
- global kill switch disabled;
- account kill switch disabled;
- strategy kill switch disabled.

A risk decision must be:

```text
APPROVED
RESIZED
HELD
REJECTED
```

Store every check and reason.

---

## 12. OMS and Execution

Support:

- market orders;
- limit orders;
- stop orders;
- stop-limit orders;
- bracket orders;
- DAY time-in-force;
- GTC time-in-force;
- order modification;
- cancellation;
- partial fills;
- multiple executions;
- commission reports;
- broker rejections;
- expired orders.

Order states:

```text
CREATED
RISK_APPROVED
QUEUED
BROKER_BLOCKED
SUBMITTED
ACKNOWLEDGED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELLED
REJECTED
EXPIRED
UNKNOWN
```

Rules:

- OMS owns the internal order state.
- Broker callbacks may be duplicated or arrive out of order.
- Fills must be based on execution events.
- Every broker command requires an idempotency key.
- Restarting any service must not duplicate an order.
- Unknown broker state must block new submissions.

---

## 13. Reconciliation

Reconcile:

- internal orders against IBKR open and completed orders;
- internal fills against IBKR executions;
- internal positions against IBKR positions;
- internal cash against IBKR account values;
- internal account state against broker account state.

On mismatch:

1. create a `ReconciliationBreak`;
2. classify severity;
3. block trading when material;
4. allow safe automatic repair where possible;
5. require explicit operator resolution otherwise;
6. preserve a complete audit history.

Run reconciliation:

- after Gateway reconnect;
- at Backend startup;
- periodically during trading;
- after uncertain order submission;
- at end of day;
- before re-enabling trading.

---

## 14. Backend API

Implement versioned APIs:

```text
/api/v1/system/
/api/v1/gateway/
/api/v1/accounts/
/api/v1/instruments/
/api/v1/portfolios/
/api/v1/positions/
/api/v1/strategies/
/api/v1/strategy-runs/
/api/v1/rebalances/
/api/v1/orders/
/api/v1/executions/
/api/v1/reconciliation/
/api/v1/risk/
/api/v1/audit/
```

Use a consistent response structure:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {}
}
```

Errors:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Readable message",
    "details": {}
  },
  "meta": {}
}
```

Use Server-Sent Events or controlled short polling for:

- Gateway state;
- account changes;
- positions;
- orders;
- executions;
- reconciliation breaks;
- risk blocks.

---

## 15. Frontend

### 15.1 Technology

Use:

- React;
- TypeScript;
- Vite;
- Zustand;
- lightweight-charts;
- Lucide icons;
- Vitest;
- Nginx for production serving.

### 15.2 Visual Design

Create a dark terminal-style interface.

Requirements:

- sharp or nearly square corners;
- compact desktop layout;
- dark background;
- restrained borders;
- monospace values for prices, IDs, quantities, logs, and status values;
- green, amber, and red state indicators;
- dense tables;
- no oversized cards;
- no soft consumer-dashboard appearance;
- no user login or registration pages.

### 15.3 Sidebar Windows

Create:

1. Overview
2. Gateway
3. Accounts
4. Portfolio
5. Strategies
6. Orders
7. Executions
8. Reconciliation
9. Risk
10. System Logs

### 15.4 Main Features

Overview:

- Gateway state;
- account status;
- NAV;
- cash;
- buying power;
- daily P&L;
- gross and net exposure;
- open-order count;
- unresolved reconciliation breaks.

Gateway:

- connection state;
- paper or live mode;
- last callback;
- reconnect control;
- noVNC link;
- broker synchronization state.

Strategies:

- five fixed strategies;
- enabled or paused state;
- configuration;
- allocation;
- last run;
- next run;
- manual run;
- generated targets.

Orders:

- order ticket;
- order validation;
- open orders;
- order history;
- modify;
- cancel;
- status timeline.

Executions:

- fills;
- average price;
- commission;
- IBKR execution identifiers;
- related internal order.

Reconciliation:

- reconciliation runs;
- breaks;
- severity;
- block state;
- resolution status.

Risk:

- limits;
- risk decisions;
- kill switches;
- blocked orders;
- exposure summaries.

System Logs:

- Backend health;
- Gateway health;
- Celery health;
- recent system events;
- errors and alerts.

The Frontend must call only the Backend.

---

## 16. Local Docker Compose

The root `docker-compose.yml` must start:

```text
backend
frontend
ib_gateway
postgres
redis
```

Requirements:

- shared private network;
- health-based dependencies;
- persistent PostgreSQL volume;
- persistent IB Gateway settings volume;
- persistent Gateway event-buffer volume;
- no Docker socket;
- no public TWS socket;
- one public port per application container;
- restart policies;
- container health checks.

Local port mappings:

```text
Frontend: 5173
Backend:  8000
Gateway:  8080
Postgres: optional localhost-only port
Redis:    optional localhost-only port
```

---

## 17. QFS Environment Configuration

### Backend

```text
PORT
APP_BASE_PATH
PUBLIC_BASE_URL
DJANGO_SECRET_KEY
DJANGO_DEBUG=false
ALLOWED_HOSTS
CORS_ALLOWED_ORIGINS
CSRF_TRUSTED_ORIGINS
DATABASE_URL
REDIS_URL
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
IB_GATEWAY_SERVICE_URL
GATEWAY_SERVICE_TOKEN
ALLOW_LIVE_TRADING=false
```

Suggested values:

```text
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
IB_GATEWAY_SERVICE_URL=https://qfsplatform.com/trading_eng_gateway/api/v1
CORS_ALLOWED_ORIGINS=https://qfsplatform.com/trading_eng_frontend
```

### Frontend

```text
PORT
VITE_API_BASE_URL
VITE_APP_BASE_PATH
```

Suggested values:

```text
VITE_API_BASE_URL=https://qfsplatform.com/trading_eng_backend/api/v1
VITE_APP_BASE_PATH=/trading_eng_frontend/
```

### IB_gateway

```text
PORT
APP_BASE_PATH
PUBLIC_BASE_URL
DJANGO_SECRET_KEY
IB_USERNAME
IB_PASSWORD
IBC_TRADING_MODE=paper
IBKR_CLIENT_ID
GATEWAY_SERVICE_TOKEN
NOVNC_PASSWORD
IBC_AUTO_RESTART_TIME
IBC_2FA_TIMEOUT
```

Suggested value:

```text
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_gateway
```

---

## 18. Paper and Live Trading Safety

Paper trading is the default.

Live order submission requires all of:

```text
IBC_TRADING_MODE=live
ALLOW_LIVE_TRADING=true
GLOBAL_KILL_SWITCH=false
ACCOUNT_KILL_SWITCH=false
BROKER_RECONCILED=true
```

The UI must clearly display whether the system is in:

```text
PAPER
LIVE
BLOCKED
DEGRADED
RECONCILING
```

Do not add any hidden method to bypass these checks.

---

## 19. Testing Requirements

### Backend Tests

- model constraints;
- strategy calculations;
- target aggregation;
- rebalance calculations;
- position sizing;
- risk approvals;
- risk resizing;
- risk rejection;
- order-state transitions;
- partial fills;
- ledger updates;
- duplicate commands;
- duplicate callbacks;
- out-of-order callbacks;
- reconciliation blocks;
- kill switches;
- Gateway client retries;
- idempotency.

### Gateway Tests

- service authentication;
- broker adapter interface;
- one connection owner;
- command idempotency;
- contract qualification;
- place order;
- modify order;
- cancel order;
- callback persistence;
- event sequencing;
- reconnect recovery;
- broker-state refresh;
- kill switch;
- no credential leakage.

Use a mocked broker adapter for automated tests.

Do not require a real IBKR account for the normal test suite.

### Frontend Tests

- routing;
- sidebar;
- API base paths;
- QFS base paths;
- status rendering;
- strategy controls;
- order validation;
- order modification;
- order cancellation;
- risk blocks;
- kill-switch confirmation;
- reconciliation screen.

### Integration Tests

- Backend-to-Gateway API contract;
- strategy-to-target flow;
- target-to-order flow;
- order-to-fill flow;
- restart recovery;
- reconciliation blocking;
- Docker Compose health smoke test.

---

## 20. Documentation

Create:

```text
README.md
docs/ARCHITECTURE.md
docs/LOCAL_DEVELOPMENT.md
docs/QFS_DEPLOYMENT.md
docs/IBKR_SETUP.md
docs/ORDER_LIFECYCLE.md
docs/RECONCILIATION.md
docs/PAPER_TO_LIVE_CHECKLIST.md
```

The root README must contain:

- project purpose;
- repository structure;
- setup commands;
- environment setup;
- local URLs;
- test commands;
- QFS deployment summary;
- paper-trading warning;
- production limitations.

---

## 21. Delivery Phases

### Phase 1: Bootstrap

- Initialize the new repository.
- Create all three application folders.
- Add Dockerfiles and Compose.
- Add environment examples.
- Add health endpoints.
- Verify independent image builds.

### Phase 2: Gateway

- Install IB Gateway and IBC.
- Add Xvfb, noVNC, Supervisor, and Nginx.
- Add Django Gateway API.
- Add the broker adapter and worker.
- Add event buffering.
- Validate one-port routing.

### Phase 3: Backend Core

- Add PostgreSQL schemas.
- Add Gateway REST client.
- Add portfolio, OMS, execution, ledger, risk, audit, and reconciliation modules.
- Add transactional outbox and idempotency.

### Phase 4: Strategies

- Implement the five fixed strategies.
- Add scheduling.
- Add target aggregation and rebalancing.
- Add strategy controls.

### Phase 5: Frontend

- Create the terminal UI.
- Add all sidebar screens.
- Connect Backend APIs.
- Add live status updates.

### Phase 6: Testing and Deployment

- Complete unit and integration tests.
- Add mocked broker scenarios.
- Add restart and reconciliation tests.
- Validate QFS routes.
- Complete deployment documentation.

---

## 22. Acceptance Criteria

The project is complete when:

1. The project exists entirely in the new repository.
2. The old repository has not been modified.
3. `docker compose up --build -d` starts the complete local stack.
4. `Backend`, `Frontend`, and `IB_gateway` build independently.
5. Each application container exposes one public port.
6. The raw TWS socket is not publicly exposed.
7. noVNC works through the Gateway HTTP port.
8. The Backend reaches IBKR only through the Gateway REST API.
9. The five strategies produce deterministic targets.
10. Risk checks run before every order.
11. Orders can be placed, modified, cancelled, partially filled, and completed.
12. Duplicate commands and callbacks do not corrupt state.
13. Restarting services does not create duplicate orders.
14. Reconciliation blocks trading when broker and internal state differ.
15. Paper trading is the default.
16. Live trading requires explicit configuration and cleared safety controls.
17. The Frontend displays Gateway, accounts, portfolios, strategies, orders, executions, risk, and reconciliation.
18. All automated tests pass.
19. No secrets are committed, returned through APIs, or written to logs.
20. QFS deployment is documented for all three URLs.

---

## 23. Codex Working Rules

Codex must:

- work only inside the new repository;
- create missing files and directories;
- never modify the old IBKR prototype repository;
- not depend on code existing outside the new repository;
- use the old repository URL only as optional read-only reference;
- implement working code rather than placeholders;
- run tests and builds after each major phase;
- keep a progress log in `docs/IMPLEMENTATION_STATUS.md`;
- record assumptions in `docs/OPEN_QUESTIONS.md`;
- proceed with sensible assumptions instead of stopping for minor ambiguity;
- keep the system paper-trading-first.
