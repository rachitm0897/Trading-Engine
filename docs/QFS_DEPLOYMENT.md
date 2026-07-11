# QFS deployment

Deploy `Backend/`, `Frontend/`, and `IB_gateway/` as three independent applications. Assign the QFS-provided `PORT` to each; publish no secondary Gateway ports.

Backend essentials:

```text
APP_BASE_PATH=/trading_eng_backend
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_backend
IB_GATEWAY_SERVICE_URL=https://qfsplatform.com/trading_eng_gateway/api/v1
CORS_ALLOWED_ORIGINS=https://qfsplatform.com/trading_eng_frontend
CSRF_TRUSTED_ORIGINS=https://qfsplatform.com/trading_eng_frontend
ALLOW_LIVE_TRADING=false
```

Frontend build variables:

```text
VITE_API_BASE_URL=https://qfsplatform.com/trading_eng_backend/api/v1
VITE_APP_BASE_PATH=/trading_eng_frontend/
VITE_GATEWAY_PUBLIC_URL=https://qfsplatform.com/trading_eng_gateway
APP_BASE_PATH=/trading_eng_frontend
```

Gateway essentials:

```text
APP_BASE_PATH=/trading_eng_gateway
PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_gateway
IBC_TRADING_MODE=paper
BROKER_ADAPTER=ib_async
```

Store Django keys, service token, IBKR credentials, and noVNC password in QFS secrets. Use the same Gateway service token in Backend and Gateway. Configure QFS to pass `X-Forwarded-Proto`, `X-Forwarded-Host`, and `X-Forwarded-Prefix`; both stripped-prefix and forwarded-prefix requests are routed. Persistent storage is required for PostgreSQL, `/data` in Gateway, and `/home/ibgateway/Jts`.

After deployment, probe each `/healthz`, verify noVNC requires its password, and confirm no raw ports 4001, 4002, 5900, 6080, or 8001 are externally reachable.
