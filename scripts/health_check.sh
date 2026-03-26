#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="${1:-${HEALTH_URL:-http://localhost/health}}"
HEALTH_ATTEMPTS="${2:-${HEALTH_ATTEMPTS:-15}}"
HEALTH_INTERVAL_SECONDS="${3:-${HEALTH_INTERVAL_SECONDS:-300}}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-10}"

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S %Z")" "$*"
}

if ! command -v curl >/dev/null 2>&1; then
  log "curl is required for health checks."
  exit 1
fi

for attempt in $(seq 1 "$HEALTH_ATTEMPTS"); do
  http_code="$(curl --silent --show-error --output /tmp/fintracker-health.$$ --write-out "%{http_code}" --max-time "$HEALTH_TIMEOUT_SECONDS" "$HEALTH_URL" || true)"
  if [ "$http_code" = "200" ]; then
    payload="$(cat /tmp/fintracker-health.$$ 2>/dev/null || true)"
    log "Health check succeeded on attempt ${attempt}/${HEALTH_ATTEMPTS}: ${payload}"
    rm -f /tmp/fintracker-health.$$
    exit 0
  fi

  payload="$(cat /tmp/fintracker-health.$$ 2>/dev/null || true)"
  log "Health check failed on attempt ${attempt}/${HEALTH_ATTEMPTS} (HTTP ${http_code:-none}). Response: ${payload:-<empty>}"
  rm -f /tmp/fintracker-health.$$

  if [ "$attempt" -lt "$HEALTH_ATTEMPTS" ]; then
    sleep "$HEALTH_INTERVAL_SECONDS"
  fi
done

log "Health check exhausted all retries."
exit 1
