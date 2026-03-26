#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_PATH="${DEPLOY_PATH:-${REPO_ROOT}}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
HEALTH_URL="${HEALTH_URL:-http://localhost/health}"
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-15}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-300}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-45}"
DEPLOY_LOG_FILE="${DEPLOY_LOG_FILE:-deployments.log}"
ROLLBACK_STATE_FILE="${ROLLBACK_STATE_FILE:-.deploy_rollback_state}"

log() {
  printf "[%s] %s\n" "$(date "+%Y-%m-%d %H:%M:%S %Z")" "$*" | tee -a "$DEPLOY_LOG_FILE"
}

read_state_value() {
  local key="$1"
  grep -E "^${key}=" "$ROLLBACK_STATE_FILE" | tail -n 1 | cut -d "=" -f2-
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i -E "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf "%s=%s\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

cd "$DEPLOY_PATH"
touch "$DEPLOY_LOG_FILE"

if [ ! -f "$ROLLBACK_STATE_FILE" ]; then
  log "Rollback state file not found: $ROLLBACK_STATE_FILE"
  exit 1
fi

previous_ref="$(read_state_value PREVIOUS_REF)"
previous_version="$(read_state_value PREVIOUS_VERSION)"
target_version="$(read_state_value TARGET_VERSION || true)"

if [ -z "$previous_ref" ] || [ -z "$previous_version" ]; then
  log "Rollback state is incomplete. Aborting rollback."
  exit 1
fi

log "Rolling back to ref ${previous_ref} and version ${previous_version}."
git fetch --all --tags --prune
git checkout --detach "$previous_ref"

touch "$ENV_FILE"
set_env_value CURRENT_VERSION "$previous_version"
set_env_value PREVIOUS_VERSION "${target_version:-$previous_version}"
set_env_value FT_APP_VERSION "$previous_version"

docker compose -f "$COMPOSE_FILE" pull || true
docker compose -f "$COMPOSE_FILE" down --remove-orphans
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

log "Waiting ${STARTUP_WAIT_SECONDS}s before rollback health check."
sleep "$STARTUP_WAIT_SECONDS"

if "$SCRIPT_DIR/health_check.sh" "$HEALTH_URL" "$HEALTH_ATTEMPTS" "$HEALTH_INTERVAL_SECONDS"; then
  log "Rollback completed successfully. Active version: ${previous_version}."
  exit 0
fi

log "Rollback health check failed. Manual intervention is required."
exit 1
