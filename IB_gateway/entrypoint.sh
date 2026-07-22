#!/bin/sh
set -eu
umask 077

# This script emits only validated, non-secret shell assignments. Validation
# completes before any runtime file, migration, or process is created.
runtime_exports="$(python /app/runtime_config.py)" || exit $?
eval "$runtime_exports"
unset runtime_exports
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
export GATEWAY_DB_PATH="${GATEWAY_DB_PATH:-/data/gateway.sqlite3}"

if [ "${1:-}" = "--validate-only" ]; then
  exit 0
fi

mkdir -p /data /home/ibgateway/.vnc /home/ibgateway/ibc /home/ibgateway/Jts /tmp/.X11-unix
chown root:root /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
chown -R ibgateway:ibgateway /data /home/ibgateway

novnc_password="$NOVNC_PASSWORD"
x11vnc -storepasswd "$novnc_password" /home/ibgateway/.vnc/passwd >/dev/null 2>&1
unset novnc_password
unset NOVNC_PASSWORD
chown -R ibgateway:ibgateway /home/ibgateway/.vnc

envsubst '${PORT}' < /app/nginx.conf.template > /etc/nginx/nginx.conf
su -s /bin/sh ibgateway -c 'cd /app && python manage.py migrate --noinput'

if [ "$BROKER_ADAPTER" = "ib_async" ]; then
  python manage.py configure_ibc
else
  rm -f /home/ibgateway/ibc/config.ini
fi
unset IB_USERNAME IB_PASSWORD

exec /usr/bin/supervisord -c /app/supervisord.conf
