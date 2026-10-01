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
log "Using container engine: ${ENGINE} (user: $(id -un), uid: $(id -u))"

compose config >/dev/null || die "compose config validation failed -- check ${DEPLOY_PATH}/.env and the compose file"

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

log "Starting the full stack"
compose up -d

compose ps
