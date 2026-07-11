#!/bin/sh
set -eu

if [ "${1:-}" = "jobmanager" ] && [ "${AUTO_SUBMIT_FLINK_JOBS:-true}" = "true" ]; then
  /docker-entrypoint.sh jobmanager &
  manager_pid=$!
  until curl -fsS http://127.0.0.1:8081/overview >/dev/null; do
    sleep 2
  done
  mkdir -p /opt/flink/checkpoints/job-ids
  for job in market_normalization bar_aggregation indicator_computation stale_price_detection stream_health; do
    restore_args=""
    id_file="/opt/flink/checkpoints/job-ids/${job}"
    if [ -f "$id_file" ]; then
      old_id="$(cat "$id_file")"
      checkpoint="$(find "/opt/flink/checkpoints/${old_id}" -name _metadata -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
      if [ -n "$checkpoint" ]; then restore_args="-s $checkpoint"; fi
    fi
    output="$(flink run -d $restore_args -py "/opt/flink/usrlib/jobs/${job}.py")"
    printf '%s\n' "$output"
    printf '%s\n' "$output" | sed -n 's/.*JobID \([0-9a-f]*\).*/\1/p' | tail -n 1 > "$id_file"
  done
  wait "$manager_pid"
else
  exec /docker-entrypoint.sh "$@"
fi
