#!/bin/sh
set -eu
if [ "${BROKER_ADAPTER:-ib_async}" = "mock" ]; then
  exec sleep infinity
fi
exec su -s /bin/bash ibgateway -c "/opt/ibc/scripts/ibcstart.sh ${TWS_MAJOR_VRSN:-1045} --gateway --tws-path=/opt/Jts --tws-settings-path=/home/ibgateway/Jts --ibc-path=/opt/ibc --ibc-ini=/home/ibgateway/ibc/config.ini --mode=${IBC_TRADING_MODE:-paper} --on2fatimeout=restart"
