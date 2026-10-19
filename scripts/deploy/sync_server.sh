#!/usr/bin/env bash
# Runs ON THE DEPLOYMENT SERVER (streamed over SSH by .github/actions/sync-server).
#
# Brings the server's copy of the deployment bundle (main branch: docker-compose.yml,
# env.example, README.md) up to date and starts the full stack (mongo, mongo-express,
# fintracker) with `compose up -d`.
#
#   1. First run: shallow clone of GIT_REF initialised in place in DEPLOY_PATH
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
  git fetch --depth 1 origin "+refs/heads/${GIT_REF}:refs/remotes/origin/${GIT_REF}"
  git reset --hard "origin/${GIT_REF}"
else
  # First run. The action has already created DEPLOY_PATH and written .env into it, so
  # `git clone` (which needs an empty directory) can't be used: initialise the clone in
  # place instead. `git checkout` refuses to overwrite untracked files, so files from a
  # manual setup (an existing docker-compose.yml, README.md, ...) are never clobbered.
  log "Initialising a clone of ${REPO_URL} (${GIT_REF}) in ${DEPLOY_PATH}"
  mkdir -p "$DEPLOY_PATH"
  cd "$DEPLOY_PATH"
  git init -q
  git remote add origin "$REPO_URL"
  if ! { git fetch --depth 1 origin "+refs/heads/${GIT_REF}:refs/remotes/origin/${GIT_REF}" && git checkout -q -B "$GIT_REF" "origin/${GIT_REF}"; }; then
    # Don't leave a half-made clone behind: the next run would take the
    # `reset --hard` path above and overwrite those files.
    rm -rf "$DEPLOY_PATH/.git"
    die "could not check out ${GIT_REF} into ${DEPLOY_PATH} -- if git reported files that 'would be overwritten', move them out of the way (keep .env) and re-run"
  fi
fi

[ -f "$DEPLOY_PATH/.env" ] || die ".env is missing in ${DEPLOY_PATH} (should have been written before this script ran)"

env_value() { grep -m1 "^${1}=" "$DEPLOY_PATH/.env" 2>/dev/null | cut -d= -f2- || true; }  # missing key -> empty, never a set -e exit

# docker-compose.yml, plus the optional nginx reverse-proxy overlay when enabled --
# included automatically so a plain `compose up -d` always matches the real running
# stack (e.g. so it doesn't drop the overlay's loopback-only port overrides).
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
  for pem in fullchain.pem privkey.pem; do
    [ -f "${nginx_certs_dir:-$DEPLOY_PATH/nginx-certs}/${pem}" ] \
      || die "FT_NGINX_ENABLED=true but ${pem} is missing in ${nginx_certs_dir:-$DEPLOY_PATH/nginx-certs} -- add the FT_NGINX_TLS_FULLCHAIN and FT_NGINX_TLS_PRIVKEY secrets (or set FT_NGINX_ENABLED=false)"
  done
  public_bind="$(env_value FT_PUBLIC_BIND)"
  [ "$public_bind" = "127.0.0.1" ] \
    || log "WARNING: FT_NGINX_ENABLED=true but FT_PUBLIC_BIND is not 127.0.0.1 -- fintracker is still reachable directly, bypassing nginx"
fi

log "Starting the full stack"
compose up -d

compose ps
