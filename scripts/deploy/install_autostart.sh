#!/usr/bin/env bash
# Run ONCE on the deployment server (not part of the CI/CD pipeline -- installing a
# systemd unit needs privileges the CI deploy user deliberately does not have) so the
# FinTracker compose stack (DEPLOY_PATH) comes back up automatically after a reboot.
#
# Usage:
#   DEPLOY_PATH=/opt/fintracker DEPLOY_USER=deploy ./install_autostart.sh
#
#   Docker          -> installs a system unit (/etc/systemd/system), run this with sudo.
#                      Optional: docker.service is enabled by default and containers
#                      already have `restart: unless-stopped`, so Docker alone recovers
#                      after a reboot without this unit -- it just gives a uniform
#                      `systemctl start|stop|status fintracker-compose` lever.
#   Rootless Podman -> installs a user unit (~DEPLOY_USER/.config/systemd/user) and
#                      enables lingering. Run this AS DEPLOY_USER (not root/sudo).
#                      This one is required: rootless Podman has no persistent daemon
#                      of its own to resurrect containers after a reboot.
set -Eeuo pipefail

log() { printf '[autostart] %s\n' "$*"; }
die() { printf '[autostart] ERROR: %s\n' "$*" >&2; exit 1; }

: "${DEPLOY_PATH:?set DEPLOY_PATH, e.g. /opt/fintracker}"
: "${DEPLOY_USER:?set DEPLOY_USER, e.g. deploy}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/../../systemctl/fintracker-compose.service"
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "Docker detected: installing a system unit that runs as ${DEPLOY_USER}"
  [ "$(id -u)" -eq 0 ] || die "run this as root (or via sudo) to install a system unit"
  sed -e "s#__DEPLOY_PATH__#${DEPLOY_PATH}#g" \
      -e "s#__USER_LINE__#User=${DEPLOY_USER}#" \
      -e "s#__WANTED_BY__#multi-user.target#" \
      "$TEMPLATE" > /etc/systemd/system/fintracker-compose.service
  systemctl daemon-reload
  systemctl enable --now fintracker-compose.service
  log "Installed. Manage it with: systemctl status|restart|stop fintracker-compose"
elif command -v podman >/dev/null 2>&1; then
  log "Podman detected: installing a user unit for ${DEPLOY_USER} (rootless)"
  [ "$(id -un)" = "$DEPLOY_USER" ] || die "run this AS ${DEPLOY_USER} (not root/sudo) -- rootless Podman units are per-user"
  mkdir -p "$HOME/.config/systemd/user"
  sed -e "s#__DEPLOY_PATH__#${DEPLOY_PATH}#g" \
      -e "/__USER_LINE__/d" \
      -e "s#__WANTED_BY__#default.target#" \
      "$TEMPLATE" > "$HOME/.config/systemd/user/fintracker-compose.service"
  sudo loginctl enable-linger "$DEPLOY_USER"
  systemctl --user daemon-reload
  systemctl --user enable --now fintracker-compose.service
  log "Installed. Manage it with: systemctl --user status|restart|stop fintracker-compose"
else
  die "neither docker nor podman is installed or usable for $(id -un)"
fi
