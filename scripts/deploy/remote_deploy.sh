#!/usr/bin/env bash
# Runs ON THE DEPLOYMENT SERVER (streamed over SSH by .github/actions/ssh-deploy).
#
# Deploys one immutable image version of the FinTracker service using the
# server's own docker compose file (never modified here):
#   1. docker pull  IMAGE:VERSION
#   2. docker tag   IMAGE:VERSION -> IMAGE:latest   (local pointer the compose file uses)
#   3. docker compose up -d --no-deps SERVICE        (only FinTracker is recreated)
#   4. verify: container running + /health reports VERSION
#   5. on failure: logs, restore the previous image, exit non-zero
#
# Never runs `down`, `-v`, volume or database commands.
#
# Required env: IMAGE, VERSION, DEPLOY_PATH
# Optional env: SERVICE (fintracker), COMPOSE_FILE, AUTO_ROLLBACK (true), HEALTH_TIMEOUT (180)
set -Eeuo pipefail

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

: "${IMAGE:?IMAGE is required}"
: "${VERSION:?VERSION is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
SERVICE="${SERVICE:-fintracker}"
COMPOSE_FILE="${COMPOSE_FILE:-}"
AUTO_ROLLBACK="${AUTO_ROLLBACK:-true}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must be MAJOR.MINOR.PATCH, got '$VERSION'"
[[ "$IMAGE" =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]] || die "IMAGE looks invalid: '$IMAGE'"
[[ "$SERVICE" =~ ^[A-Za-z0-9._-]+$ ]] || die "SERVICE looks invalid: '$SERVICE'"
[[ "$HEALTH_TIMEOUT" =~ ^[0-9]+$ ]] || die "HEALTH_TIMEOUT must be seconds"

command -v docker >/dev/null || die "docker is not installed or not on PATH for $(id -un)"
docker compose version >/dev/null 2>&1 || die "docker compose v2 plugin is required"
[ -d "$DEPLOY_PATH" ] || die "DEPLOY_PATH does not exist: $DEPLOY_PATH"
cd "$DEPLOY_PATH"

# Compose files may reference ${FINTRACKER_VERSION}; plain ":latest" works too.
export FINTRACKER_VERSION="$VERSION"

compose() {
  if [ -n "$COMPOSE_FILE" ]; then docker compose -f "$COMPOSE_FILE" "$@"; else docker compose "$@"; fi
}

compose config --services | grep -qx "$SERVICE" \
  || die "service '$SERVICE' not found in the compose file in $DEPLOY_PATH"
if ! compose config --images | grep -qxE "${IMAGE}:(latest|${VERSION})"; then
  die "compose service '$SERVICE' must use image ${IMAGE}:latest (or ${IMAGE}:\${FINTRACKER_VERSION}); found: $(compose config --images | tr '\n' ' ')"
fi

container_id() { compose ps -q "$SERVICE" 2>/dev/null | head -n 1; }

prev_cid="$(container_id || true)"
prev_image_id=""
prev_version="none"
if [ -n "$prev_cid" ]; then
  prev_image_id="$(docker inspect --format '{{.Image}}' "$prev_cid" 2>/dev/null || true)"
  prev_version="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$prev_image_id" 2>/dev/null || true)"
  prev_version="${prev_version:-unknown}"
fi
log "Currently running: ${prev_version}"

log "Pulling ${IMAGE}:${VERSION}"
docker pull --quiet "${IMAGE}:${VERSION}" >/dev/null || die "docker pull ${IMAGE}:${VERSION} failed"
new_image_id="$(docker image inspect --format '{{.Id}}' "${IMAGE}:${VERSION}")"

# Point the local :latest at the exact version being deployed (does not touch Docker Hub).
docker tag "${IMAGE}:${VERSION}" "${IMAGE}:latest"

log "Recreating service '${SERVICE}' (other services untouched)"
compose up -d --no-deps "$SERVICE"

health_version() {
  compose exec -T "$SERVICE" python -c \
    "import json, os, urllib.request as u; print(json.load(u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)).get('version', ''))" \
    2>/dev/null | tr -d '\r' | tail -n 1
}

verify() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) cid state image_id health reported
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid="$(container_id || true)"
    if [ -n "$cid" ]; then
      state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
      image_id="$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null || echo "")"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
      if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
        log "Container ${state}."
        return 1
      fi
      if [ "$state" = "running" ] && [ "$image_id" = "$new_image_id" ] && [ "$health" != "unhealthy" ]; then
        reported="$(health_version || true)"
        if [ "$reported" = "$VERSION" ]; then
          log "Health OK: /health reports ${reported} (container health: ${health})"
          return 0
        fi
      fi
    fi
    sleep 5
  done
  log "Timed out after ${HEALTH_TIMEOUT}s waiting for a healthy ${VERSION}"
  return 1
}

if verify; then
  compose ps "$SERVICE"
  echo "DEPLOYED_VERSION=${VERSION}"
  echo "PREVIOUS_VERSION=${prev_version}"
  exit 0
fi

log "Deployment verification FAILED. Diagnostics:"
compose ps || true
compose logs --no-color --tail=100 "$SERVICE" || true

if [ "$AUTO_ROLLBACK" = "true" ] && [ -n "$prev_image_id" ] && [ "$prev_image_id" != "$new_image_id" ]; then
  log "Restoring previous version (${prev_version}) so the service stays up"
  docker tag "$prev_image_id" "${IMAGE}:latest"
  if [[ "$prev_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    export FINTRACKER_VERSION="$prev_version"
  else
    unset FINTRACKER_VERSION   # ${FINTRACKER_VERSION:-latest} -> the re-pointed :latest
  fi
  compose up -d --no-deps "$SERVICE" || log "Restore attempt failed; manual action required"
  compose ps "$SERVICE" || true
fi
die "deployment of ${VERSION} failed"
