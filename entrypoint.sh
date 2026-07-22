#!/bin/sh
set -eu
export PORT="${PORT:-8000}"
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
export RESEARCH_MAX_PARALLEL_DATA_TASKS="${RESEARCH_MAX_PARALLEL_DATA_TASKS:-8}"
export RESEARCH_MAX_PARALLEL_BACKTEST_TASKS="${RESEARCH_MAX_PARALLEL_BACKTEST_TASKS:-8}"
python manage.py migrate --noinput
exec supervisord -c /app/supervisord.conf
