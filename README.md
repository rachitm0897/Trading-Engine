# Frontend

React/TypeScript operations terminal served by Nginx on one configurable port. It calls only the Backend API and includes Overview, Gateway, Accounts, Portfolio, Strategies, Orders, Executions, Reconciliation, Risk, and System Logs. There are intentionally no authentication screens.

```bash
cp .env.example .env
npm install
npm run dev
npm test
npm run build
```

Set `VITE_API_BASE_URL` to the public Backend `/api/v1` URL and `VITE_APP_BASE_PATH` to `/` locally or `/trading_eng_frontend/` on QFS. Health: `GET /healthz`.

