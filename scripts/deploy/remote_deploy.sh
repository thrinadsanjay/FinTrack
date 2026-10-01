#!/usr/bin/env bash
# Runs ON THE DEPLOYMENT SERVER (streamed over SSH by .github/actions/ssh-deploy).
#
# Deploys one immutable image version of the FinTracker service using the
# server's own compose file (never modified here):
#   1. ENGINE pull  IMAGE:VERSION                     (ENGINE is docker, or rootless podman)
#   2. ENGINE tag   IMAGE:VERSION -> IMAGE:latest   (local pointer the compose file uses)
#   3. compose up -d --no-deps SERVICE                (only FinTracker is recreated)
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

[ -d "$DEPLOY_PATH" ] || die "DEPLOY_PATH does not exist: $DEPLOY_PATH"
cd "$DEPLOY_PATH"

# Compose files may reference ${FINTRACKER_VERSION}; plain ":latest" works too.
export FINTRACKER_VERSION="$VERSION"

# --- container engine / compose detection: Docker, or rootless Podman ---
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENGINE=docker
  docker compose version >/dev/null 2>&1 || die "docker is present but the compose v2 plugin is missing"
  compose() { if [ -n "$COMPOSE_FILE" ]; then docker compose -f "$COMPOSE_FILE" "$@"; else docker compose "$@"; fi; }
elif command -v podman >/dev/null 2>&1; then
  ENGINE=podman
  if podman compose version >/dev/null 2>&1; then
    compose() { if [ -n "$COMPOSE_FILE" ]; then podman compose -f "$COMPOSE_FILE" "$@"; else podman compose "$@"; fi; }
  elif command -v podman-compose >/dev/null 2>&1; then
    compose() { if [ -n "$COMPOSE_FILE" ]; then podman-compose -f "$COMPOSE_FILE" "$@"; else podman-compose "$@"; fi; }
  else
    die "podman is installed but no compose implementation (podman compose / podman-compose) was found"
  fi
else
  die "neither docker nor podman is installed or usable for $(id -un)"
fi
log "Using container engine: ${ENGINE}"

compose config --services | grep -qx "$SERVICE" \
  || die "service '$SERVICE' not found in the compose file in $DEPLOY_PATH"
if ! compose config --images | grep -qxE "${IMAGE}:(latest|${VERSION})"; then
  die "compose service '$SERVICE' must use image ${IMAGE}:latest (or ${IMAGE}:\${FINTRACKER_VERSION}); found: $(compose config --images | tr '\n' ' ')"
fi

# Docker auto-creates a missing bind-mount host directory; rootless Podman does not
# (fails with "statfs ...: no such file or directory"). Create it if missing so this
# doesn't depend on the engine. Never touched if it already exists (real certs may live
# there).
certs_dir="$(grep -m1 '^FT_CERTS_DIR=' "$DEPLOY_PATH/.env" 2>/dev/null | cut -d= -f2-)"
certs_dir="${certs_dir:-$DEPLOY_PATH/certs}"
if [ ! -d "$certs_dir" ]; then
  log "Creating missing certs mount directory: ${certs_dir}"
  mkdir -p "$certs_dir" \
    || die "could not create ${certs_dir} -- create it manually (e.g. sudo mkdir -p ${certs_dir} && sudo chown $(id -un): ${certs_dir}) and re-run"
  chmod 700 "$certs_dir" 2>/dev/null || true
fi

container_id() { compose ps -q "$SERVICE" 2>/dev/null | head -n 1; }

prev_cid="$(container_id || true)"
prev_image_id=""
prev_version="none"
if [ -n "$prev_cid" ]; then
  prev_image_id="$($ENGINE inspect --format '{{.Image}}' "$prev_cid" 2>/dev/null || true)"
  prev_version="$($ENGINE image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$prev_image_id" 2>/dev/null || true)"
  prev_version="${prev_version:-unknown}"
fi
log "Currently running: ${prev_version}"

log "Pulling ${IMAGE}:${VERSION}"
$ENGINE pull --quiet "${IMAGE}:${VERSION}" >/dev/null || die "$ENGINE pull ${IMAGE}:${VERSION} failed"
new_image_id="$($ENGINE image inspect --format '{{.Id}}' "${IMAGE}:${VERSION}")"

# Point the local :latest at the exact version being deployed (does not touch the registry).
$ENGINE tag "${IMAGE}:${VERSION}" "${IMAGE}:latest"

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
      state="$($ENGINE inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
      image_id="$($ENGINE inspect --format '{{.Image}}' "$cid" 2>/dev/null || echo "")"
      health="$($ENGINE inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
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
  $ENGINE tag "$prev_image_id" "${IMAGE}:latest"
  if [[ "$prev_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    export FINTRACKER_VERSION="$prev_version"
  else
    unset FINTRACKER_VERSION   # ${FINTRACKER_VERSION:-latest} -> the re-pointed :latest
  fi
  compose up -d --no-deps "$SERVICE" || log "Restore attempt failed; manual action required"
  compose ps "$SERVICE" || true
fi
die "deployment of ${VERSION} failed"
