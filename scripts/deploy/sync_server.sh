#!/usr/bin/env bash
# Runs ON THE DEPLOYMENT SERVER (streamed over SSH by .github/actions/sync-server).
#
# Brings the server's copy of the deployment bundle (main branch: docker-compose.yml,
# env.example, README.md) up to date and starts the full stack (mongo, mongo-express,
# fintracker) with `compose up -d`.
#
#   1. First run: git clone --depth 1 --branch GIT_REF into DEPLOY_PATH
#      Later runs: git fetch + git reset --hard origin/GIT_REF
#      (reset --hard only touches tracked files; .env and anything else untracked,
#      e.g. TLS certs, are left alone)
#   2. Detect a working container engine: Docker, or rootless Podman
#      (podman compose, falling back to the standalone podman-compose)
#   3. compose config (validates the file + .env substitution)
#   4. compose up -d
#
# The .env file is written separately, before this script runs, by the same
# action; this script only checks that it exists.
#
# Required env: REPO_URL, DEPLOY_PATH
# Optional env: GIT_REF (main), COMPOSE_FILE
set -Eeuo pipefail

log() { printf '[sync] %s\n' "$*"; }
die() { printf '[sync] ERROR: %s\n' "$*" >&2; exit 1; }

: "${REPO_URL:?REPO_URL is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
GIT_REF="${GIT_REF:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-}"

[[ "$GIT_REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "GIT_REF looks invalid: '$GIT_REF'"
[[ "$DEPLOY_PATH" = /* ]] || die "DEPLOY_PATH must be an absolute path, got '$DEPLOY_PATH'"

command -v git >/dev/null || die "git is not installed or not on PATH for $(id -un)"

if [ -d "$DEPLOY_PATH/.git" ]; then
  log "Updating existing clone at ${DEPLOY_PATH}"
  cd "$DEPLOY_PATH"
  git remote set-url origin "$REPO_URL"
  git fetch --depth 1 origin "$GIT_REF"
  git reset --hard "origin/${GIT_REF}"
else
  [ -d "$DEPLOY_PATH" ] && [ -n "$(ls -A "$DEPLOY_PATH" 2>/dev/null)" ] \
    && die "DEPLOY_PATH ($DEPLOY_PATH) exists, is non-empty, and is not a git clone; refusing to overwrite it"
  log "Cloning ${REPO_URL} (${GIT_REF}) into ${DEPLOY_PATH}"
  mkdir -p "$DEPLOY_PATH"
  git clone --depth 1 --branch "$GIT_REF" --single-branch "$REPO_URL" "$DEPLOY_PATH"
  cd "$DEPLOY_PATH"
fi

[ -f "$DEPLOY_PATH/.env" ] || die ".env is missing in ${DEPLOY_PATH} (should have been written before this script ran)"

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
log "Using container engine: ${ENGINE} (user: $(id -un), uid: $(id -u))"

compose config >/dev/null || die "compose config validation failed -- check ${DEPLOY_PATH}/.env and the compose file"

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

log "Starting the full stack"
compose up -d

compose ps
