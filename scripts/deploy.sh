#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_PATH="${DEPLOY_PATH:-${REPO_ROOT}}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-Dev}"
DEPLOY_BUMP_KIND="${DEPLOY_BUMP_KIND:-}"
DEPLOY_COMMIT_MESSAGE="${DEPLOY_COMMIT_MESSAGE:-manual deployment}"
DEPLOY_TRIGGER_ACTOR="${DEPLOY_TRIGGER_ACTOR:-unknown}"
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

read_env_value() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d "=" -f2- || true
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

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Required command not found: $1"
    exit 1
  fi
}

require_command git
require_command docker
require_command curl

cd "$DEPLOY_PATH"
touch "$DEPLOY_LOG_FILE"
touch "$ENV_FILE"

if [ -z "$DEPLOY_BUMP_KIND" ]; then
  DEPLOY_BUMP_KIND="$($SCRIPT_DIR/version.sh infer-bump "$DEPLOY_COMMIT_MESSAGE")"
fi

current_ref="$(git rev-parse HEAD)"
current_version="$(read_env_value CURRENT_VERSION)"
if [ -z "$current_version" ]; then
  current_version="$(read_env_value FT_APP_VERSION)"
fi
if [ -z "$current_version" ]; then
  current_version="v0.0.0"
fi

log "Starting deployment for branch ${DEPLOY_BRANCH}. Triggered by ${DEPLOY_TRIGGER_ACTOR}."
log "Commit summary: ${DEPLOY_COMMIT_MESSAGE}"
log "Current version: ${current_version}; bump kind: ${DEPLOY_BUMP_KIND}."

git fetch origin "$DEPLOY_BRANCH" --tags --prune
git checkout --detach "origin/${DEPLOY_BRANCH}"
target_ref="$(git rev-parse HEAD)"
target_version="$($SCRIPT_DIR/version.sh next --env-file "$ENV_FILE" --bump-kind "$DEPLOY_BUMP_KIND")"

cat > "$ROLLBACK_STATE_FILE" <<EOF_STATE
PREVIOUS_REF=${current_ref}
PREVIOUS_VERSION=${current_version}
TARGET_REF=${target_ref}
TARGET_VERSION=${target_version}
DEPLOYED_AT=$(date "+%Y-%m-%d %H:%M:%S %Z")
EOF_STATE

set_env_value PREVIOUS_VERSION "$current_version"
set_env_value CURRENT_VERSION "$target_version"
set_env_value FT_APP_VERSION "$target_version"

log "Updated version markers: PREVIOUS_VERSION=${current_version}, CURRENT_VERSION=${target_version}."
docker compose -f "$COMPOSE_FILE" pull || true
docker compose -f "$COMPOSE_FILE" down --remove-orphans
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

log "Waiting ${STARTUP_WAIT_SECONDS}s for services to start before health checks."
sleep "$STARTUP_WAIT_SECONDS"

if "$SCRIPT_DIR/health_check.sh" "$HEALTH_URL" "$HEALTH_ATTEMPTS" "$HEALTH_INTERVAL_SECONDS"; then
  log "Deployment succeeded. Version ${target_version} is healthy on ${target_ref}."
  exit 0
fi

log "Deployment health check failed for version ${target_version}. Starting rollback."
if "$SCRIPT_DIR/rollback.sh"; then
  log "Rollback completed after failed deployment. Restored version ${current_version}."
else
  log "Rollback failed after deployment failure. Manual intervention is required."
fi

exit 1
