FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=https://qfsplatform.com/trading_eng_backend/api/v1
ARG VITE_APP_BASE_PATH=/trading_eng_frontend/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_APP_BASE_PATH=$VITE_APP_BASE_PATH
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
COPY .env.example .env
RUN npm run build

FROM nginx:1.27-alpine
ENV PORT=5173 \
    APP_BASE_PATH=/trading_eng_frontend \
    PUBLIC_BASE_URL=https://qfsplatform.com/trading_eng_frontend \
    BACKEND_API_URL=https://qfsplatform.com/trading_eng_backend/api/v1
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
COPY runtime-config.template.js /etc/trading-engine/runtime-config.template.js
COPY docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh
EXPOSE 5173
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -q --spider http://127.0.0.1:${PORT:-5173}/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
