# FinTracker container runtime detection -- shared by every deploy script.
#
#   CI:      the SSH actions stream this file followed by the script (cat runtime.sh X.sh | ssh bash -s)
#   Server:  ./fintrack and install_autostart.sh source it (published to `main` as lib/runtime.sh)
#
# Defines functions only (safe to source under `set -Eeuo pipefail`). Call ft_detect_runtime once:
#
#   engine  ...  the container CLI: docker | podman
#   compose ...  the compose tool, with "${COMPOSE_F_ARGS[@]}" (if set) prepended
#
# Supported, autodetected in this order:
#   engine:   Docker (real daemon, usable by this user)  ->  Podman (rootful or rootless)
#             (a `docker` that is podman's emulation shim counts as Podman)
#   compose:  Docker -> `docker compose` (v2 plugin) -> `docker-compose` (standalone)
#             Podman -> `podman-compose` -> `podman compose` (any provider)
#                       -> `docker-compose` against the Podman API socket
# Overrides (environment, or .env on the server -- the scripts pass them through):
#   FT_CONTAINER_ENGINE = docker | podman
#   FT_COMPOSE          = "docker compose" | docker-compose | podman-compose | "podman compose"

_ft_rt_log() { printf '[runtime] %s\n' "$*" >&2; }

# Last lines of a command's stderr+stdout, for error messages.
_ft_rt_err() { "$@" 2>&1 >/dev/null | tail -n 8; }

_ft_rt_is_podman_shim() {
  # podman-docker installs a `docker` that runs podman.
  docker --version 2>/dev/null | grep -qi podman
}

# Why the user can't run containers -- appended to "no usable engine" errors.
_ft_rt_diagnostics() {
  local procs limit mem
  procs="$(ps -u "$(id -u)" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
  limit="$(ulimit -u 2>/dev/null || echo '?')"
  mem="$(free -h 2>/dev/null | awk '/^Mem:/{print $7" available of "$2}')"
  _ft_rt_log "user $(id -un) (uid $(id -u)): ${procs} processes (ulimit -u ${limit}); memory ${mem:-unknown}"
  _ft_rt_log "busiest commands: $(ps -u "$(id -u)" -o comm= 2>/dev/null | sort | uniq -c | sort -rn | head -n 5 | tr -s ' ' | tr '\n' ';')"
}

_ft_rt_try_docker() {
  command -v docker >/dev/null 2>&1 || { _ft_rt_reasons+=("docker: not installed"); return 1; }
  if _ft_rt_is_podman_shim; then
    _ft_rt_reasons+=("docker: is podman's emulation shim (treated as podman)"); return 1
  fi
  local err
  if ! err="$(_ft_rt_err docker info)"; then
    case "$err" in
      *"permission denied"*) err="permission denied on the Docker socket -- add $(id -un) to the docker group (sudo usermod -aG docker $(id -un)) and log in again" ;;
      *"Cannot connect"*|*"Is the docker daemon running"*) err="daemon not running -- sudo systemctl enable --now docker" ;;
    esac
    _ft_rt_reasons+=("docker: not usable: ${err:-docker info failed}"); return 1
  fi
}

_ft_rt_try_podman() {
  command -v podman >/dev/null 2>&1 || { _ft_rt_reasons+=("podman: not installed"); return 1; }
  local err
  if ! err="$(_ft_rt_err podman info)"; then
    # A crash here is usually the user out of processes/threads or memory
    # ("pthread_create failed: Resource temporarily unavailable").
    _ft_rt_reasons+=("podman: not usable: ${err:-podman info failed}"); return 1
  fi
}

# Sets FT_COMPOSE_CMD (array) and FT_COMPOSE_NAME for the chosen engine.
_ft_rt_pick_compose() {
  local want="${FT_COMPOSE:-}" sock
  local -a candidates
  if [ "$FT_ENGINE" = docker ]; then
    candidates=("docker compose" "docker-compose")
  else
    candidates=("podman-compose" "podman compose" "docker-compose")
  fi
  local c
  if [ -n "$want" ]; then
    for c in "${candidates[@]}"; do [ "$c" = "$want" ] && break; c=""; done
    if [ -z "$c" ]; then
      _ft_rt_log "FT_COMPOSE='${want}' is not valid with ${FT_ENGINE} (use one of: $(printf '"%s" ' "${candidates[@]}"))"
      return 1
    fi
    candidates=("$want")
  fi
  for c in "${candidates[@]}"; do
    case "$c" in
      "docker compose")
        docker compose version >/dev/null 2>&1 && { FT_COMPOSE_CMD=(docker compose); FT_COMPOSE_NAME="$c"; return 0; } ;;
      "docker-compose")
        command -v docker-compose >/dev/null 2>&1 || continue
        if [ "$FT_ENGINE" = podman ]; then
          # docker-compose talks to Podman through its Docker-compatible API socket.
          sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock"
          [ "$(id -u)" -eq 0 ] && sock=/run/podman/podman.sock
          [ -S "$sock" ] || { _ft_rt_log "docker-compose found but the Podman socket ${sock} is not active (systemctl --user enable --now podman.socket)"; continue; }
          export DOCKER_HOST="unix://${sock}"
        fi
        docker-compose version >/dev/null 2>&1 && { FT_COMPOSE_CMD=(docker-compose); FT_COMPOSE_NAME="$c"; return 0; } ;;
      "podman-compose")
        command -v podman-compose >/dev/null 2>&1 && podman-compose version >/dev/null 2>&1 \
          && { FT_COMPOSE_CMD=(podman-compose); FT_COMPOSE_NAME="$c"; return 0; } ;;
      "podman compose")
        # Quiet the "Executing external compose provider" banner.
        export PODMAN_COMPOSE_WARNING_LOGS=false
        podman compose version >/dev/null 2>&1 && { FT_COMPOSE_CMD=(podman compose); FT_COMPOSE_NAME="$c"; return 0; } ;;
    esac
  done
  _ft_rt_log "no working compose tool for ${FT_ENGINE}; tried: $(printf '"%s" ' "${candidates[@]}")"
  if [ "$FT_ENGINE" = podman ]; then
    _ft_rt_log "install one, e.g.: sudo dnf install podman-compose  |  sudo apt install podman-compose  |  pip install --user podman-compose"
  else
    _ft_rt_log "install one, e.g.: sudo apt install docker-compose-plugin  |  sudo dnf install docker-compose-plugin"
  fi
  return 1
}

# Detects engine + compose. Returns non-zero (after explaining why) when nothing usable exists.
ft_detect_runtime() {
  _ft_rt_reasons=()
  FT_ENGINE=""
  case "${FT_CONTAINER_ENGINE:-}" in
    "")     if _ft_rt_try_docker; then FT_ENGINE=docker; elif _ft_rt_try_podman; then FT_ENGINE=podman; fi ;;
    docker) _ft_rt_try_docker && FT_ENGINE=docker ;;
    podman) _ft_rt_try_podman && FT_ENGINE=podman ;;
    *)      _ft_rt_log "FT_CONTAINER_ENGINE must be docker or podman, got '${FT_CONTAINER_ENGINE}'"; return 1 ;;
  esac
  if [ -z "$FT_ENGINE" ]; then
    _ft_rt_log "no usable container engine for $(id -un)${FT_CONTAINER_ENGINE:+ (FT_CONTAINER_ENGINE=${FT_CONTAINER_ENGINE})}:"
    local r; for r in "${_ft_rt_reasons[@]}"; do _ft_rt_log "  - ${r}"; done
    _ft_rt_diagnostics
    return 1
  fi
  _ft_rt_pick_compose || return 1
  engine()  { "$FT_ENGINE" "$@"; }
  compose() { "${FT_COMPOSE_CMD[@]}" ${COMPOSE_F_ARGS[@]+"${COMPOSE_F_ARGS[@]}"} "$@"; }
  local mode=""
  [ "$FT_ENGINE" = podman ] && mode="$( [ "$(id -u)" -eq 0 ] && echo ', rootful' || echo ', rootless')"
  _ft_rt_log "engine: ${FT_ENGINE} ($("$FT_ENGINE" --version 2>/dev/null | head -n1)${mode}) | compose: ${FT_COMPOSE_NAME} | user: $(id -un) (uid $(id -u))"
  ft_select_mongo_tag
}

# MongoDB image tag for this host, exported as FT_MONGO_IMAGE_TAG (compose prefers the
# environment over .env). An explicit FT_MONGO_IMAGE_TAG (environment or .env) always wins,
# then the image of the project's existing mongo container. Otherwise (fresh install):
#   CPU without AVX                              -> 4.4  (MongoDB >= 5.0 needs AVX)
#   EL7 family (Oracle Linux / RHEL / CentOS 7)  -> 5.0  (Ubuntu 20.04 base, glibc 2.31:
#   or Docker < 20.10.10                                  older seccomp profiles break the
#                                                         clone3-based threads of glibc >= 2.34,
#                                                         used by mongo >= 6.0 images)
#   anything else                                -> latest (the compose file's default)
# Never downgrade an existing data volume: once a newer MongoDB has opened it, pin the
# tag you run in FT_MONGO_IMAGE_TAG.
FT_MONGO_TAG_LEGACY="5.0"
FT_MONGO_TAG_NO_AVX="4.4"
ft_select_mongo_tag() {
  local tag="${FT_MONGO_IMAGE_TAG:-}" reason=""
  [ -n "$tag" ] || tag="$(sed -n 's/^FT_MONGO_IMAGE_TAG=["'\'']\{0,1\}\([A-Za-z0-9_.-]*\).*/\1/p' .env 2>/dev/null | head -n1)"
  if [ -n "$tag" ]; then
    _ft_rt_log "mongo image tag: ${tag} (FT_MONGO_IMAGE_TAG)"
    return 0
  fi

  # Auto-selection is for fresh installs only: an existing mongo container keeps its
  # image, so a deploy can never swap the MongoDB version under an existing data volume.
  local existing
  existing="$(engine ps -aq --filter "label=com.docker.compose.project=$(ft_compose_project)" \
                --filter label=com.docker.compose.service=mongo 2>/dev/null | head -n1)"
  [ -n "$existing" ] && existing="$(engine inspect --format '{{.Config.Image}}' "$existing" 2>/dev/null || true)"
  if [[ "$existing" == *mongo:* ]]; then
    export FT_MONGO_IMAGE_TAG="${existing##*:}"
    _ft_rt_log "mongo image tag: ${FT_MONGO_IMAGE_TAG} (kept from the existing mongo container; set FT_MONGO_IMAGE_TAG to change it)"
    return 0
  fi

  local os_id="" os_ver="" docker_ver=""
  if [ -r /etc/os-release ]; then
    os_id="$(. /etc/os-release && echo "${ID:-} ${ID_LIKE:-}")"
    os_ver="$(. /etc/os-release && echo "${VERSION_ID:-}")"
  fi
  [ "${FT_ENGINE:-}" = docker ] && docker_ver="$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)"

  if [ -r /proc/cpuinfo ] && ! grep -qw avx /proc/cpuinfo; then
    tag="$FT_MONGO_TAG_NO_AVX"; reason="CPU has no AVX"
  elif [[ " ${os_id} " =~ \ (ol|rhel|centos)\  ]] && [[ "$os_ver" == 7* ]]; then
    tag="$FT_MONGO_TAG_LEGACY"; reason="EL7-family host (${os_id%% *} ${os_ver})"
  elif [ -n "$docker_ver" ] && [ "$(printf '%s\n' "${docker_ver%%-*}" 20.10.10 | sort -V | head -n1)" != 20.10.10 ]; then
    tag="$FT_MONGO_TAG_LEGACY"; reason="Docker ${docker_ver} < 20.10.10"
  fi

  if [ -n "$tag" ]; then
    export FT_MONGO_IMAGE_TAG="$tag"
    _ft_rt_log "mongo image tag: ${tag} (auto: ${reason}; set FT_MONGO_IMAGE_TAG to override)"
  else
    _ft_rt_log "mongo image tag: latest (auto; set FT_MONGO_IMAGE_TAG to pin a version)"
  fi
}

# Services in the compose project (works with every compose tool).
# Output must be non-empty: docker-compose v1 answers an unknown option with usage on
# stderr and exit code 0, so success alone doesn't mean the option worked.
ft_compose_services() {
  local out
  out="$(compose config --services 2>/dev/null)" && [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
  compose config 2>/dev/null | awk '
    /^services:/ {in_s=1; next}
    in_s && /^[^ #]/ {in_s=0}
    in_s && /^  [A-Za-z0-9._-]+:[[:space:]]*$/ {sub(/^  /,""); sub(/:.*/,""); print}'
}

# Image references in the compose project (`config --images` is docker-compose-only).
ft_compose_images() {
  local out
  out="$(compose config --images 2>/dev/null)" && [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
  compose config 2>/dev/null | awk '/^ +image:/ {v=$2; gsub(/["\047]/,"",v); print v}'
}

# Compose project name, resolved the way compose does: COMPOSE_PROJECT_NAME (environment,
# then .env), else the file's top-level `name:` (older bundles), else the folder.
ft_compose_project() {
  if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then echo "$COMPOSE_PROJECT_NAME"; return; fi
  local n
  n="$(sed -n 's/^COMPOSE_PROJECT_NAME=["'\'']\{0,1\}\([A-Za-z0-9_.-]*\).*/\1/p' .env 2>/dev/null | head -n1)"
  [ -n "$n" ] && { echo "$n"; return; }
  local f="docker-compose.yml" i
  local -a fa=(${COMPOSE_F_ARGS[@]+"${COMPOSE_F_ARGS[@]}"})
  for ((i = 0; i + 1 < ${#fa[@]}; i++)); do
    [ "${fa[$i]}" = "-f" ] && { f="${fa[$((i + 1))]}"; break; }
  done
  n="$(sed -n 's/^name:[[:space:]]*["'\'']\{0,1\}\([A-Za-z0-9_.-]*\).*/\1/p' "$f" 2>/dev/null | head -n1)"
  [ -n "$n" ] && { echo "$n"; return; }
  basename "$(pwd)" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

# Container ID of SERVICE (running preferred, else the newest stopped one). Uses the
# com.docker.compose.* labels that docker compose, docker-compose and podman-compose all set.
ft_service_container() {
  local svc="$1" project id
  project="$(ft_compose_project)"
  local -a f=(--filter "label=com.docker.compose.service=${svc}")
  id="$(engine ps -q "${f[@]}" --filter "label=com.docker.compose.project=${project}" --filter status=running 2>/dev/null | head -n1)"
  [ -n "$id" ] || id="$(engine ps -aq "${f[@]}" --filter "label=com.docker.compose.project=${project}" 2>/dev/null | head -n1)"
  [ -n "$id" ] || id="$(engine ps -q "${f[@]}" --filter status=running 2>/dev/null | head -n1)"
  printf '%s' "$id"
}
