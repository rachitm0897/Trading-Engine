#!/bin/sh
set -eu

BACKEND_API_URL="${BACKEND_API_URL:-${VITE_API_BASE_URL:-https://qfsplatform.com/trading_eng_backend/api/v1}}"
export BACKEND_API_URL
envsubst '${BACKEND_API_URL}' < /etc/trading-engine/runtime-config.template.js > /usr/share/nginx/html/runtime-config.js
