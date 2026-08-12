#!/bin/sh
set -eu

export PORT="${PORT:-8000}"
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"
export RESEARCH_MAX_PARALLEL_DATA_TASKS="${RESEARCH_MAX_PARALLEL_DATA_TASKS:-8}"
export RESEARCH_MAX_PARALLEL_BACKTEST_TASKS="${RESEARCH_MAX_PARALLEL_BACKTEST_TASKS:-8}"

echo "Checking PostgreSQL connectivity..."
python scripts/ensure_database.py

echo "Running Django migrations..."
python manage.py migrate --noinput

if [ "${CLEANUP_DATABASE_ON_START:-false}" = "true" ]; then
  echo "CLEANUP_DATABASE_ON_START=true: deleting all database rows..."
  python manage.py flush --noinput
  echo "Database rows deleted. Set CLEANUP_DATABASE_ON_START=false before the next restart."
fi

echo "Checking required Kafka topics..."
python scripts/ensure_kafka_topics.py

echo "Checking required Flink jobs..."
if python -u scripts/ensure_flink_jobs.py; then
  echo "Flink job bootstrap finished."
else
  bootstrap_status=$?
  echo "Flink job bootstrap failed with status ${bootstrap_status}; continuing so Backend diagnostics remain available." >&2
fi

echo "Starting Backend services..."
exec supervisord -c /app/supervisord.conf
