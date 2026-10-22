#!/usr/bin/env bash
# Runs ON THE GITHUB ACTIONS RUNNER, after a deploy/sync. Streams deploy/lib/runtime.sh +
# scripts/deploy/server_report.sh to the server over SSH and prints the Markdown report
# to the log and the job summary ($GITHUB_STEP_SUMMARY). Informational only: always
# exits 0, so a reporting problem can never fail a deployment.
#
# Required env: DEPLOY_PATH, SERVER_HOST, SERVER_USER
# Optional env: SERVER_PORT (22), COMPOSE_FILE, REPORT_TITLE, SSH_STRICT (yes|no, default yes)
set -uo pipefail

ws="${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
remote_env="$(printf 'DEPLOY_PATH=%q COMPOSE_FILE=%q' "$DEPLOY_PATH" "${COMPOSE_FILE:-}")"

report="$(
  ssh -i "$HOME/.ssh/fintracker_deploy" \
      -p "${SERVER_PORT:-22}" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking="${SSH_STRICT:-yes}" \
      -o UserKnownHostsFile="$HOME/.ssh/known_hosts" \
      -o ConnectTimeout=20 \
      "${SERVER_USER}@${SERVER_HOST}" \
      "${remote_env} bash -s" \
      < <(cat "$ws/deploy/lib/runtime.sh" "$ws/scripts/deploy/server_report.sh") 2>/dev/null
)" || true
[ -n "$report" ] || report="> ⚠️ Could not collect the server report (SSH or remote script failed)."

body="$(printf '## %s\n\n%s\n' "${REPORT_TITLE:-Deployment report}" "$report")"
printf '%s\n' "$body"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && printf '%s\n\n' "$body" >> "$GITHUB_STEP_SUMMARY"
exit 0
