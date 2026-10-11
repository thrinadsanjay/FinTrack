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

[ -d "$DEPLOY_PATH" ] || die "DEPLOY_PATH does not exist: $DEPLOY_PATH -- on a fresh server, run 'Publish deployment bundle to main' (Actions -> Run workflow) once: it creates the folder, writes .env, clones main and starts the stack; then re-run this deploy"
cd "$DEPLOY_PATH"
# DEPLOY_PATH must be the server's clone of `main` (the folder publish-main.yml syncs).
compose_main="${COMPOSE_FILE:-docker-compose.yml}"
[ -f "$compose_main" ] \
  || die "no ${compose_main} in DEPLOY_PATH=${DEPLOY_PATH} -- set the DEPLOY_PATH variable to the folder that holds the clone of main (the one the 'Sync bundle to the server' job uses)"
[ -f .env ] || die "no .env in DEPLOY_PATH=${DEPLOY_PATH} -- run 'Publish deployment bundle to main' (manual run) to write it, or check DEPLOY_PATH"

# Compose files may reference ${FINTRACKER_VERSION}; plain ":latest" works too.
export FINTRACKER_VERSION="$VERSION"

env_value() { grep -m1 "^${1}=" "$DEPLOY_PATH/.env" 2>/dev/null | cut -d= -f2- || true; }  # missing key -> empty, never a set -e exit

# docker-compose.yml, plus the optional nginx reverse-proxy overlay when enabled --
# included automatically so this single-service recreate doesn't drop the overlay's
# loopback-only port overrides on fintracker.
COMPOSE_F_ARGS=()
[ -n "$COMPOSE_FILE" ] && COMPOSE_F_ARGS+=(-f "$COMPOSE_FILE")
if [ "$(env_value FT_NGINX_ENABLED)" = "true" ] && [ -f "$DEPLOY_PATH/docker-compose.nginx.yml" ]; then
  # Any -f disables compose's default file lookup, so the base file must be named
  # explicitly before the overlay (the overlay alone has no ft-net, mongo, ...).
  [ -n "$COMPOSE_FILE" ] || COMPOSE_F_ARGS+=(-f docker-compose.yml)
  COMPOSE_F_ARGS+=(-f docker-compose.nginx.yml)
  log "Reverse-proxy overlay enabled: including docker-compose.nginx.yml"
fi

# --- container runtime: deploy/lib/runtime.sh (streamed ahead of this script by CI) ---
# Autodetects docker / podman and docker compose / docker-compose / podman-compose /
# podman compose; FT_CONTAINER_ENGINE / FT_COMPOSE in .env override the choice.
declare -F ft_detect_runtime >/dev/null || . "$(dirname "${BASH_SOURCE[0]}")/../../deploy/lib/runtime.sh"
FT_CONTAINER_ENGINE="${FT_CONTAINER_ENGINE:-$(env_value FT_CONTAINER_ENGINE)}"
FT_COMPOSE="${FT_COMPOSE:-$(env_value FT_COMPOSE)}"
ft_detect_runtime || die "no usable container runtime for $(id -un) -- see the [runtime] lines above"

ft_compose_services | grep -qx "$SERVICE" \
  || die "service '$SERVICE' not found in the compose file in $DEPLOY_PATH"
if ! ft_compose_images | grep -qxE "${IMAGE}:(latest|${VERSION})"; then
  die "compose service '$SERVICE' must use image ${IMAGE}:latest (or ${IMAGE}:\${FINTRACKER_VERSION}); found: $(ft_compose_images | tr '\n' ' ')"
fi

# Docker auto-creates a missing bind-mount host directory; rootless Podman does not
# (fails with "statfs ...: no such file or directory"). Create any that are missing so
# this doesn't depend on the engine. Never touched if it already exists (real certs may
# live there).
ensure_mount_dir() {
  local dir="$1"
  [ -d "$dir" ] && return 0
  log "Creating missing mount directory: ${dir}"
  mkdir -p "$dir" \
    || die "could not create ${dir} -- create it manually (e.g. sudo mkdir -p ${dir} && sudo chown $(id -un): ${dir}) and re-run"
  chmod 700 "$dir" 2>/dev/null || true
}
certs_dir="$(env_value FT_CERTS_DIR)"
ensure_mount_dir "${certs_dir:-$DEPLOY_PATH/certs}"
if [ "$(env_value FT_NGINX_ENABLED)" = "true" ]; then
  nginx_certs_dir="$(env_value FT_NGINX_CERTS_DIR)"
  ensure_mount_dir "${nginx_certs_dir:-$DEPLOY_PATH/nginx-certs}"
  public_bind="$(env_value FT_PUBLIC_BIND)"
  [ "$public_bind" = "127.0.0.1" ] \
    || log "WARNING: FT_NGINX_ENABLED=true but FT_PUBLIC_BIND is not 127.0.0.1 -- fintracker is still reachable directly, bypassing nginx"
fi

container_id() { ft_service_container "$SERVICE"; }

prev_cid="$(container_id || true)"
prev_image_id=""
prev_version="none"
if [ -n "$prev_cid" ]; then
  prev_image_id="$(engine inspect --format '{{.Image}}' "$prev_cid" 2>/dev/null || true)"
  prev_version="$(engine image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$prev_image_id" 2>/dev/null || true)"
  prev_version="${prev_version:-unknown}"
fi
log "Currently running: ${prev_version}"

log "Pulling ${IMAGE}:${VERSION}"
engine pull --quiet "${IMAGE}:${VERSION}" >/dev/null || die "${FT_ENGINE} pull ${IMAGE}:${VERSION} failed"
new_image_id="$(engine image inspect --format '{{.Id}}' "${IMAGE}:${VERSION}")"

# Point the local :latest at the exact version being deployed (does not touch the registry).
engine tag "${IMAGE}:${VERSION}" "${IMAGE}:latest"

log "Recreating service '${SERVICE}' (other services untouched)"
compose up -d --no-deps "$SERVICE"

health_version() {
  local cid
  cid="$(ft_service_container "$SERVICE")"
  [ -n "$cid" ] || return 1
  engine exec "$cid" python -c \
    "import json, os, urllib.request as u; print(json.load(u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)).get('version', ''))" \
    2>/dev/null | tr -d '\r' | tail -n 1
}

verify() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) cid state image_id health reported
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid="$(container_id || true)"
    if [ -n "$cid" ]; then
      state="$(engine inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
      image_id="$(engine inspect --format '{{.Image}}' "$cid" 2>/dev/null || echo "")"
      health="$(engine inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
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
diag_cid="$(ft_service_container "$SERVICE")"
[ -z "$diag_cid" ] || engine logs --tail 100 "$diag_cid" 2>&1 || true

if [ "$AUTO_ROLLBACK" = "true" ] && [ -n "$prev_image_id" ] && [ "$prev_image_id" != "$new_image_id" ]; then
  log "Restoring previous version (${prev_version}) so the service stays up"
  engine tag "$prev_image_id" "${IMAGE}:latest"
  if [[ "$prev_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    export FINTRACKER_VERSION="$prev_version"
  else
    unset FINTRACKER_VERSION   # ${FINTRACKER_VERSION:-latest} -> the re-pointed :latest
  fi
  compose up -d --no-deps "$SERVICE" || log "Restore attempt failed; manual action required"
  compose ps "$SERVICE" || true
fi
die "deployment of ${VERSION} failed"
