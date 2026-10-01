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

env_value() { grep -m1 "^${1}=" "$DEPLOY_PATH/.env" 2>/dev/null | cut -d= -f2-; }

# docker-compose.yml, plus the optional nginx reverse-proxy overlay when enabled --
# included automatically so a plain `compose up -d` always matches the real running
# stack (e.g. so it doesn't drop the overlay's loopback-only port overrides).
COMPOSE_F_ARGS=()
[ -n "$COMPOSE_FILE" ] && COMPOSE_F_ARGS+=(-f "$COMPOSE_FILE")
if [ "$(env_value FT_NGINX_ENABLED)" = "true" ] && [ -f "$DEPLOY_PATH/docker-compose.nginx.yml" ]; then
  COMPOSE_F_ARGS+=(-f docker-compose.nginx.yml)
  log "Reverse-proxy overlay enabled: including docker-compose.nginx.yml"
fi

# --- container engine / compose detection: Docker, or rootless Podman ---
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENGINE=docker
  docker compose version >/dev/null 2>&1 || die "docker is present but the compose v2 plugin is missing"
  compose() { docker compose "${COMPOSE_F_ARGS[@]}" "$@"; }
elif command -v podman >/dev/null 2>&1; then
  ENGINE=podman
  if podman compose version >/dev/null 2>&1; then
    compose() { podman compose "${COMPOSE_F_ARGS[@]}" "$@"; }
  elif command -v podman-compose >/dev/null 2>&1; then
    compose() { podman-compose "${COMPOSE_F_ARGS[@]}" "$@"; }
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
