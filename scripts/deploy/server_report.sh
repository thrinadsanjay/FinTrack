#!/usr/bin/env bash
# Runs ON THE DEPLOYMENT SERVER (streamed over SSH, after deploy/lib/runtime.sh, by
# scripts/deploy/report.sh). Prints a Markdown report of the running stack:
# server IP, overall status, nginx on/off, containers (status, ports) and the URLs
# each service is reachable on. Read-only; never changes anything.
#
# Required env: DEPLOY_PATH
# Optional env: COMPOSE_FILE
set -uo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
COMPOSE_FILE="${COMPOSE_FILE:-}"
cd "$DEPLOY_PATH" || { echo "> ⚠️ Report skipped: ${DEPLOY_PATH} not found on the server."; exit 0; }

env_value() { grep -m1 "^${1}=" .env 2>/dev/null | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }

nginx_enabled=false
[ "$(env_value FT_NGINX_ENABLED)" = "true" ] && [ -f docker-compose.nginx.yml ] && nginx_enabled=true
COMPOSE_F_ARGS=()
[ -n "$COMPOSE_FILE" ] && COMPOSE_F_ARGS+=(-f "$COMPOSE_FILE")
if [ "$nginx_enabled" = true ]; then
  [ -n "$COMPOSE_FILE" ] || COMPOSE_F_ARGS+=(-f docker-compose.yml)
  COMPOSE_F_ARGS+=(-f docker-compose.nginx.yml)
fi

FT_CONTAINER_ENGINE="${FT_CONTAINER_ENGINE:-$(env_value FT_CONTAINER_ENGINE)}"
FT_COMPOSE="${FT_COMPOSE:-$(env_value FT_COMPOSE)}"
ft_detect_runtime 2>/dev/null || { echo "> ⚠️ Report skipped: no usable container runtime."; exit 0; }
project="$(ft_compose_project)"

# --- facts -------------------------------------------------------------------------
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$ip" ] || ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}')"
ip="${ip:-unknown}"
host_name="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo unknown)"

# Host CPU %: two /proc/stat samples 1s apart (busy = everything but idle + iowait).
cpu_sample() { awk '/^cpu /{idle=$5+$6; t=0; for (i=2;i<=NF;i++) t+=$i; print t, idle}' /proc/stat 2>/dev/null; }
cpu_pct=""
s1="$(cpu_sample)"
if [ -n "$s1" ]; then
  sleep 1; s2="$(cpu_sample)"
  cpu_pct="$(echo "$s1 $s2" | awk '{dt=$3-$1; di=$4-$2; if (dt>0) printf "%.0f", 100*(dt-di)/dt}')"
fi
cores="$(nproc 2>/dev/null || echo '?')"
load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"

# RAM / swap from /proc/meminfo (MemAvailable = what applications can still use).
# Kernels without MemAvailable: estimate it as free + buffers + page cache.
read -r mem_total mem_avail swap_total swap_free <<< "$(awk '
  /^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^MemFree:/{f=$2} /^Buffers:/{b=$2} /^Cached:/{c=$2}
  /^SwapTotal:/{st=$2} /^SwapFree:/{sf=$2}
  END {if (a == "") a=f+b+c; print t+0, a+0, st+0, sf+0}' /proc/meminfo 2>/dev/null)"
gib() { awk -v k="$1" 'BEGIN {printf "%.1f GiB", k/1048576}'; }
pct() { awk -v u="$1" -v t="$2" 'BEGIN {if (t>0) printf "%.0f", 100*u/t}'; }
mem_used=$(( ${mem_total:-0} - ${mem_avail:-0} ))
mem_pct="$(pct "$mem_used" "${mem_total:-0}")"
swap_used=$(( ${swap_total:-0} - ${swap_free:-0} ))
swap_pct="$(pct "$swap_used" "${swap_total:-0}")"

# Disk: the deploy folder's filesystem and the engine's data root (images, volumes --
# MongoDB data lives there), listed once each when they share a filesystem.
engine_root="$(engine info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
[ -n "$engine_root" ] || engine_root="$(engine info --format '{{.Store.GraphRoot}}' 2>/dev/null || true)"
disk_rows="$(for d in "$DEPLOY_PATH" ${engine_root:+"$engine_root"} /; do
  # Parse around the "NN%" column so spaces in the device or mount path can't shift fields.
  df -Pk "$d" 2>/dev/null | awk -v d="$d" 'NR==2 {
    for (i=NF; i>0; i--) if ($i ~ /^[0-9]+%$/) break
    m=$(i+1); for (j=i+2; j<=NF; j++) m=m " " $j
    print m "|" d "|" $(i-3) "|" $(i-2) "|" $i }'
done | awk -F'|' '!seen[$1]++')"

# Per-container CPU / RAM (one sample).
stats="$(engine stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}|{{.MemUsage}}' 2>/dev/null || true)"

app_port="$(env_value PORT)"; app_port="${app_port:-8000}"
public_port="$(env_value FT_PUBLIC_PORT)"; public_port="${public_port:-8008}"
public_bind="$(env_value FT_PUBLIC_BIND)"; public_bind="${public_bind:-0.0.0.0}"
me_port="$(env_value FT_MONGO_EXPRESS_PORT)"; me_port="${me_port:-8081}"
me_bind="$(env_value FT_MONGO_EXPRESS_BIND)"; me_bind="${me_bind:-127.0.0.1}"
mongo_port="$(env_value FT_MONGO_PORT)"; mongo_port="${mongo_port:-27017}"
mongo_bind="$(env_value FT_MONGO_BIND)"; mongo_bind="${mongo_bind:-127.0.0.1}"
domain="$(env_value FT_DOMAIN)"
app_sub="$(env_value FT_FINTRACKER_SUBDOMAIN)"; app_sub="${app_sub:-fintracker}"
me_sub="$(env_value FT_MONGO_EXPRESS_SUBDOMAIN)"; me_sub="${me_sub:-mongo}"
https_port="$(env_value FT_NGINX_HTTPS_PORT)"; https_port="${https_port:-443}"

# Container rows: name | service | image | status | ports (docker and podman templates differ).
if [ "$FT_ENGINE" = podman ]; then
  fmt='{{.Names}}|{{index .Labels "com.docker.compose.service"}}|{{.Image}}|{{.Status}}|{{.Ports}}'
else
  fmt='{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.Image}}|{{.Status}}|{{.Ports}}'
fi
rows="$(engine ps -a --filter "label=com.docker.compose.project=${project}" --format "$fmt" 2>/dev/null | sort -t'|' -k2)"

total=0; up=0; unhealthy=0
while IFS='|' read -r _ _ _ st _; do
  [ -n "$st" ] || continue
  total=$((total + 1))
  case "$st" in Up*|up*|running*) up=$((up + 1)) ;; esac
  case "$st" in *unhealthy*|*starting*) unhealthy=$((unhealthy + 1)) ;; esac
done <<< "$rows"

http_code() { curl -ks -o /dev/null -m 10 -w '%{http_code}' "$@" 2>/dev/null || true; }
app_health="$(http_code "http://127.0.0.1:${public_port}/health")"
nginx_health=""
if [ "$nginx_enabled" = true ] && [ -n "$domain" ]; then
  nginx_health="$(http_code --resolve "${app_sub}.${domain}:${https_port}:127.0.0.1" "https://${app_sub}.${domain}:${https_port}/health")"
fi

if [ "$total" -gt 0 ] && [ "$up" -eq "$total" ] && [ "$unhealthy" -eq 0 ] && [ "$app_health" = 200 ] \
   && { [ -z "$nginx_health" ] || [ "$nginx_health" = 200 ]; }; then
  status="✅ Healthy"
else
  status="⚠️ Degraded"
fi

# --- report ------------------------------------------------------------------------
cell() { printf '%s' "${1:--}" | sed 's/|/\\|/g'; }
# Usage percentage with a traffic light: < 75 green, < 90 amber, >= 90 red.
level() {
  [ -n "$1" ] || { echo "n/a"; return; }
  local n="${1%%.*}"; n="${n//[!0-9]/}"; n="${n:-0}"
  if [ "$n" -ge 90 ]; then echo "🔴 $1%"; elif [ "$n" -ge 75 ]; then echo "🟠 $1%"; else echo "🟢 $1%"; fi
}
ok() { [ "$1" = 200 ] && echo "✅ ${1}" || echo "❌ ${1:-no response}"; }
host_url() {  # bind address, port, service:port, [scheme]
  local scheme="${4:-http}"
  if [ "$1" = 127.0.0.1 ] || [ "$1" = localhost ]; then
    echo "| \`${scheme}://127.0.0.1:$2\` (server only / SSH tunnel) | \`$3\` |"
  else
    echo "| \`${scheme}://${ip}:$2\` | \`$3\` |"
  fi
}

echo "### 🖥️ Server status"
echo
echo "| | |"
echo "|---|---|"
echo "| Hostname | \`${host_name}\` |"
echo "| IP Address | \`${ip}\` |"
echo "| Status | ${status} — ${up}/${total} containers up |"
echo "| Nginx | $([ "$nginx_enabled" = true ] && echo True || echo False) |"
echo "| App health (\`/health\`) | $(ok "$app_health") |"
[ -n "$nginx_health" ] && echo "| App via nginx (HTTPS) | $(ok "$nginx_health") |"
echo "| Engine | ${FT_ENGINE} ($(${FT_ENGINE} --version 2>/dev/null | head -n1)), ${FT_COMPOSE_NAME} |"
echo "| Compose project | \`${project}\` in \`${DEPLOY_PATH}\` |"
echo
echo "### 📊 Host resources"
echo
echo "| Resource | Usage | Details |"
echo "|---|---|---|"
echo "| CPU | $(level "$cpu_pct") | ${cores} cores, load avg ${load:-n/a} (1/5/15 min) |"
echo "| RAM | $(level "$mem_pct") | $(gib "$mem_used") used of $(gib "${mem_total:-0}") |"
[ "${swap_total:-0}" -gt 0 ] && echo "| Swap | $(level "$swap_pct") | $(gib "$swap_used") used of $(gib "$swap_total") |"
while IFS='|' read -r mnt dir size used dpct; do
  [ -n "$mnt" ] || continue
  label="$mnt"
  [ "$dir" = "$DEPLOY_PATH" ] && label="${mnt} (deploy folder)"
  [ -n "$engine_root" ] && [ "$dir" = "$engine_root" ] && label="${mnt} (${FT_ENGINE} images + volumes)"
  echo "| Disk \`$(cell "$label")\` | $(level "${dpct%\%}") | $(gib "$used") used of $(gib "$size") |"
done <<< "$disk_rows"
echo
echo "### 📦 Containers"
echo
echo "| Container | Service | Image | Status | CPU | RAM | Ports |"
echo "|---|---|---|---|---|---|---|"
if [ -n "$rows" ]; then
  while IFS='|' read -r name svc image st ports; do
    c_cpu=""; c_mem=""; c_usage=""
    IFS='|' read -r _ c_cpu c_mem c_usage <<< "$(printf '%s\n' "$stats" | awk -F'|' -v n="$name" '$1==n {print; exit}')"
    c_usage="${c_usage%% / *}"
    echo "| $(cell "$name") | $(cell "$svc") | \`$(cell "$image")\` | $(cell "$st") | $(cell "$c_cpu") | $(cell "${c_mem:+${c_mem} (${c_usage})}") | $(cell "${ports//, /<br>}") |"
  done <<< "$rows"
else
  echo "| _no containers found for project ${project}_ | | | | | | |"
fi
echo
echo "### 🌐 Hosted URLs"
echo
echo "| URL | → container (service:port) |"
echo "|---|---|"
if [ "$nginx_enabled" = true ] && [ -n "$domain" ]; then
  sfx=""; [ "$https_port" = 443 ] || sfx=":${https_port}"
  echo "| \`https://${app_sub}.${domain}${sfx}\` | \`nginx:443 → fintracker:${app_port}\` |"
  echo "| \`https://${me_sub}.${domain}${sfx}\` | \`nginx:443 → mongo-express:8081\` |"
fi
host_url "$public_bind" "$public_port" "fintracker:${app_port}"
host_url "$me_bind" "$me_port" "mongo-express:8081"
host_url "$mongo_bind" "$mongo_port" "mongo:27017" mongodb
exit 0
