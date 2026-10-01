#!/usr/bin/env bash
# Runs ON THE TEST SERVER (streamed over SSH by .github/actions/test-deploy).
#
# Unlike scripts/deploy/sync_server.sh, this never clones or resets anything --
# the test server already has its own docker-compose.yml (same shape as
# deploy/docker-compose.yml), which this script assumes is already in place.
# The .env written just before this runs sets FINTRACKER_VERSION=<version>-test,
# so `compose pull && compose up -d` picks up the test image tag without any
# compose-file change.
#
#   1. compose config (validates the file + the just-written .env)
#   2. compose pull (fetches the -test image tag)
#   3. compose up -d (recreates the full stack)
#   4. verify: container running, not unhealthy, /health responds
#
# Required env: DEPLOY_PATH
# Optional env: SERVICE (fintracker), COMPOSE_FILE, HEALTH_TIMEOUT (120)
set -Eeuo pipefail

log() { printf '[test-deploy] %s\n' "$*"; }
die() { printf '[test-deploy] ERROR: %s\n' "$*" >&2; exit 1; }

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
SERVICE="${SERVICE:-fintracker}"
COMPOSE_FILE="${COMPOSE_FILE:-}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

[[ "$DEPLOY_PATH" = /* ]] || die "DEPLOY_PATH must be an absolute path, got '$DEPLOY_PATH'"
[[ "$SERVICE" =~ ^[A-Za-z0-9._-]+$ ]] || die "SERVICE looks invalid: '$SERVICE'"
[ -d "$DEPLOY_PATH" ] || die "DEPLOY_PATH does not exist on the test server: $DEPLOY_PATH (it must already hold a compose file -- see docs/CICD.md)"
cd "$DEPLOY_PATH"
[ -f .env ] || die ".env is missing in ${DEPLOY_PATH} (should have been written before this script ran)"

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
log "Using container engine: ${ENGINE} (user: $(id -un))"

compose config --services | grep -qx "$SERVICE" \
  || die "service '$SERVICE' not found in the compose file in $DEPLOY_PATH"

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

log "Pulling the test image"
compose pull "$SERVICE"

log "Recreating the stack"
compose up -d

health_ok() {
  compose exec -T "$SERVICE" python -c \
    "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % __import__('os').environ.get('PORT', '8000'), timeout=4).status == 200 else 1)" \
    >/dev/null 2>&1
}

verify() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) cid state health
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid="$(compose ps -q "$SERVICE" 2>/dev/null | head -n 1)"
    if [ -n "$cid" ]; then
      state="$($ENGINE inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
      health="$($ENGINE inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo none)"
      if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
        log "Container ${state}."
        return 1
      fi
      if [ "$state" = "running" ] && [ "$health" != "unhealthy" ] && health_ok; then
        log "Health OK (container health: ${health})"
        return 0
      fi
    fi
    sleep 5
  done
  log "Timed out after ${HEALTH_TIMEOUT}s waiting for a healthy container"
  return 1
}

if verify; then
  compose ps "$SERVICE"
  exit 0
fi

log "Test deployment verification FAILED. Diagnostics:"
compose ps || true
compose logs --no-color --tail=100 "$SERVICE" || true
die "test deployment failed verification"
