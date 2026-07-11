#!/bin/sh
set -eu
if [ "${BROKER_ADAPTER:-ib_async}" = "mock" ]; then
  exec sleep infinity
fi
exec su -s /bin/sh ibgateway -c "/opt/ibc/gatewaystart.sh -inline"

