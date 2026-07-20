#!/bin/sh
set -eu
export PORT="${PORT:-8080}" FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}" APP_BASE_PATH="/${APP_BASE_PATH#/}"
[ "$APP_BASE_PATH" = "/" ] && export APP_BASE_PATH=""
ibc_mode="$(printf '%s' "${IBC_TRADING_MODE:-paper}" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
case "$ibc_mode" in paper|live) export IBC_TRADING_MODE="$ibc_mode" ;; *) echo "IBC_TRADING_MODE must be exactly paper or live" >&2; exit 64 ;; esac
mkdir -p /data /home/ibgateway/.vnc /home/ibgateway/ibc
chown -R ibgateway:ibgateway /data /home/ibgateway
novnc_password="${NOVNC_PASSWORD:-change-me}"
x11vnc -storepasswd "$novnc_password" /home/ibgateway/.vnc/passwd >/dev/null
unset novnc_password
chown -R ibgateway:ibgateway /home/ibgateway/.vnc
envsubst '${PORT} ${APP_BASE_PATH}' < /app/nginx.conf.template > /etc/nginx/nginx.conf
python manage.py migrate --noinput
python manage.py configure_ibc
chown ibgateway:ibgateway /home/ibgateway/ibc/config.ini
exec supervisord -c /app/supervisord.conf
