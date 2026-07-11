#!/bin/sh
set -eu
export PORT="${PORT:-8080}" FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}" APP_BASE_PATH="/${APP_BASE_PATH#/}"
[ "$APP_BASE_PATH" = "/" ] && export APP_BASE_PATH=""
mkdir -p /data /home/ibgateway/.vnc /home/ibgateway/ibc
chown -R ibgateway:ibgateway /data /home/ibgateway
printf '%s\n' "${NOVNC_PASSWORD:-change-me}" | x11vnc -storepasswd - /home/ibgateway/.vnc/passwd >/dev/null
chown -R ibgateway:ibgateway /home/ibgateway/.vnc
envsubst '${PORT} ${APP_BASE_PATH}' < /app/nginx.conf.template > /etc/nginx/nginx.conf
python manage.py migrate --run-syncdb --noinput
python manage.py configure_ibc
exec supervisord -c /app/supervisord.conf

