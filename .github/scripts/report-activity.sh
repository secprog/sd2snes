#!/usr/bin/env bash
set -u

container_name=${1:?Usage: report-activity.sh CONTAINER [INTERVAL_SECONDS]}
interval=${2:-60}
sleep_pid=
trap 'if [[ -n "$sleep_pid" ]]; then kill "$sleep_pid" 2>/dev/null || true; fi; exit 0' TERM INT

while true; do
  sleep "$interval" &
  sleep_pid=$!
  wait "$sleep_pid" || exit 0
  sleep_pid=
  if [[ "$(docker inspect "$container_name" --format '{{.State.Running}}' 2>/dev/null)" != true ]]; then
    continue
  fi
  echo "::group::Vendor tool activity $(date -u +%FT%TZ)"
  docker stats --no-stream --format 'CPU {{.CPUPerc}} | memory {{.MemUsage}}' "$container_name" || true
  docker top "$container_name" -eo pid,etime,time,pcpu,rss,comm || true
  echo '::endgroup::'
done
