#!/usr/bin/env bash

# DO NOT use strict -e globally (we control failures manually)
set -uo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$(pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
APP_SERVICE="${APP_SERVICE:-fintracker}"
IMAGE_REPO="${IMAGE_REPO:?IMAGE_REPO is required}"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG is required}"
PROD_TAG="${PROD_TAG:-prod}"
BACKUP_TAG="${BACKUP_TAG:-backup}"

HEALTH_URL="${HEALTH_URL:-http://localhost:8008/health}"
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-3}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-300}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-20}"

DEPLOY_STATUS_FILE="${DEPLOY_STATUS_FILE:-.deploy-status}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1"
    exit 2
  fi
}

record_status() {
  printf '%s\n' "$1" > "$DEPLOY_STATUS_FILE"
}

health_check() {
  attempt=1

  while [ "$attempt" -le "$HEALTH_ATTEMPTS" ]; do
    log "Performing health check attempt ${attempt}/${HEALTH_ATTEMPTS}..."

    response="$(curl --silent --show-error --max-time 20 "$HEALTH_URL" || true)"

    if echo "$response" | grep -q '"status":"ok"'; then
      log "Health check passed."
      return 0
    fi

    log "Health failed. Response: ${response:-<empty>}"

    if [ "$attempt" -lt "$HEALTH_ATTEMPTS" ]; then
      sleep "$HEALTH_INTERVAL_SECONDS"
    fi

    attempt=$((attempt + 1))
  done

  return 1
}

restart_backend() {
  log "Stopping existing container..."
  docker compose -f "$COMPOSE_FILE" down "$APP_SERVICE" 2>/dev/null || true

  log "Starting container..."
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$APP_SERVICE"

  log "Container state:"
  docker ps -a | grep fintracker || true
}

restore_backup() {
  backup_ref="${IMAGE_REPO}:${BACKUP_TAG}"

  if ! docker image inspect "$backup_ref" >/dev/null 2>&1; then
    log "Backup image not found."
    return 1
  fi

  log "Restoring backup image ${backup_ref}..."
  docker tag "$backup_ref" "${IMAGE_REPO}:${PROD_TAG}"

  restart_backend
  sleep "$STARTUP_WAIT_SECONDS"

  log "Running rollback health check..."

  if health_check; then
    record_status rollback
    log "Rollback SUCCESS"
    return 0
  fi

  record_status total_failure
  log "Rollback FAILED"
  return 1
}

# ===========================
# START EXECUTION
# ===========================

require_command docker
require_command curl

cd "$DEPLOY_DIR"
record_status deploying

log "Using HEALTH_URL=$HEALTH_URL"

# Backup current image
current_container_id="$(docker compose -f "$COMPOSE_FILE" ps -q "$APP_SERVICE" 2>/dev/null || true)"

if [ -n "$current_container_id" ]; then
  current_image_id="$(docker inspect --format '{{.Image}}' "$current_container_id")"
  docker tag "$current_image_id" "${IMAGE_REPO}:${BACKUP_TAG}"
  log "Backup created: ${IMAGE_REPO}:${BACKUP_TAG}"
else
  log "No running container found (first deploy?)"
fi

# Pull new image
target_image="${IMAGE_REPO}:${IMAGE_TAG}"
log "Pulling image ${target_image}..."
docker pull "$target_image"

docker tag "$target_image" "${IMAGE_REPO}:${PROD_TAG}"

# Restart service
log "Deploying new version..."
restart_backend

log "Waiting ${STARTUP_WAIT_SECONDS}s for app startup..."
sleep "$STARTUP_WAIT_SECONDS"

# ===========================
# HEALTH CHECK (SAFE MODE)
# ===========================

log "Starting health check..."

set +e
health_check
health_status=$?
set -e

if [ "$health_status" -eq 0 ]; then
  record_status success
  log "Deployment SUCCESS"
  exit 0
fi

# ===========================
# FAILURE → ROLLBACK
# ===========================

log "Deployment FAILED → Starting rollback..."

if restore_backup; then
  exit 10
fi

exit 20