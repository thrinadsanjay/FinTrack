#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="${1:-${HEALTH_URL:-http://localhost:8000/health}}"
HEALTH_ATTEMPTS="${2:-${HEALTH_ATTEMPTS:-3}}"
HEALTH_INTERVAL_SECONDS="${3:-${HEALTH_INTERVAL_SECONDS:-300}}"
HEALTH_EXPECTED="${HEALTH_EXPECTED:-{\"Error\":200,\"status\":\"ok\"}}"

attempt=1
while [ "$attempt" -le "$HEALTH_ATTEMPTS" ]; do
  response="$(curl --silent --show-error --max-time 20 "$HEALTH_URL" || true)"
  if [ "$response" = "$HEALTH_EXPECTED" ]; then
    printf 'Health check passed on attempt %s/%s.\n' "$attempt" "$HEALTH_ATTEMPTS"
    exit 0
  fi

  printf 'Health check failed on attempt %s/%s. Response: %s\n' "$attempt" "$HEALTH_ATTEMPTS" "${response:-<empty>}"
  if [ "$attempt" -lt "$HEALTH_ATTEMPTS" ]; then
    sleep "$HEALTH_INTERVAL_SECONDS"
  fi
  attempt=$((attempt + 1))
done

exit 1
