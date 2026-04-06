#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$(pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
APP_SERVICE="${APP_SERVICE:-fintracker}"
IMAGE_REPO="${IMAGE_REPO:?IMAGE_REPO is required}"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG is required}"
PROD_TAG="${PROD_TAG:-prod}"
BACKUP_TAG="${BACKUP_TAG:-backup}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
HEALTH_EXPECTED="${HEALTH_EXPECTED:-{\"Error\":200,\"status\":\"ok\"}}"
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-3}"
HEALTH_INTERVAL_SECONDS="${HEALTH_INTERVAL_SECONDS:-300}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-15}"
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
  attempt=5
  while [ "$attempt" -le "$HEALTH_ATTEMPTS" ]; do
    response="$(curl --silent --show-error --max-time 20 "$HEALTH_URL" || true)"
    if [ "$response" = "$HEALTH_EXPECTED" ]; then
      log "Health check passed on attempt ${attempt}/${HEALTH_ATTEMPTS}."
      return 0
    fi

    log "Health check failed on attempt ${attempt}/${HEALTH_ATTEMPTS}. Response: ${response:-<empty>}"
    if [ "$attempt" -lt "$HEALTH_ATTEMPTS" ]; then
      sleep "$HEALTH_INTERVAL_SECONDS"
    fi
    attempt=$((attempt + 1))
  done

  return 1
}

restart_backend() {
  docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$APP_SERVICE"
}

restore_backup() {
  backup_ref="${IMAGE_REPO}:${BACKUP_TAG}"
  if ! docker image inspect "$backup_ref" >/dev/null 2>&1; then
    log "Backup image ${backup_ref} not found."
    return 1
  fi

  log "Restoring backup image ${backup_ref}."
  docker tag "$backup_ref" "${IMAGE_REPO}:${PROD_TAG}"
  restart_backend
  sleep "$STARTUP_WAIT_SECONDS"

  if health_check; then
    record_status rollback
    log "Rollback completed successfully."
    return 0
  fi

  record_status total_failure
  log "Rollback health check failed."
  return 1
}

require_command docker
require_command curl

cd "$DEPLOY_DIR"
record_status deploying

current_container_id="$(docker compose -f "$COMPOSE_FILE" ps -q "$APP_SERVICE" 2>/dev/null || true)"
if [ -n "$current_container_id" ]; then
  current_image_id="$(docker inspect --format '{{.Image}}' "$current_container_id")"
  docker tag "$current_image_id" "${IMAGE_REPO}:${BACKUP_TAG}"
  log "Backed up current image to ${IMAGE_REPO}:${BACKUP_TAG}."
else
  log "No running ${APP_SERVICE} container found. Continuing without backup image tag."
fi

target_image="${IMAGE_REPO}:${IMAGE_TAG}"
log "Pulling ${target_image}."
docker pull "$target_image"
docker tag "$target_image" "${IMAGE_REPO}:${PROD_TAG}"

log "Restarting backend service ${APP_SERVICE} only."
restart_backend
sleep "$STARTUP_WAIT_SECONDS"

if health_check; then
  record_status success
  log "Deployment succeeded with ${target_image}."
  exit 0
fi

log "Deployment health check failed. Starting rollback."
if restore_backup; then
  exit 10
fi

exit 20
