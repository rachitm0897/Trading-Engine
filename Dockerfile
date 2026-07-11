FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_APP_BASE_PATH=/
ARG VITE_GATEWAY_PUBLIC_URL=http://localhost:8080
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_APP_BASE_PATH=$VITE_APP_BASE_PATH VITE_GATEWAY_PUBLIC_URL=$VITE_GATEWAY_PUBLIC_URL
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV PORT=5173 APP_BASE_PATH=
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -q --spider http://127.0.0.1:${PORT:-5173}/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
