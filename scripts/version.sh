#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  scripts/version.sh infer-bump [message]
  scripts/version.sh current [--env-file PATH]
  scripts/version.sh next [--env-file PATH] [--bump-kind major|minor|patch]
USAGE
}

trim_quotes() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  printf "%s" "$value"
}

read_env_value() {
  local env_file="$1"
  local key="$2"
  if [ ! -f "$env_file" ]; then
    return 1
  fi

  local line
  line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 1
  fi

  trim_quotes "${line#*=}"
}

normalize_version() {
  local raw="$1"
  raw="$(trim_quotes "$raw")"
  raw="${raw#v}"
  IFS=. read -r major minor patch <<EOF_PARTS
${raw:-0.0.0}
EOF_PARTS
  major="${major:-0}"
  minor="${minor:-0}"
  patch="${patch:-0}"
  printf "%s %s %s\n" "$major" "$minor" "$patch"
}

bump_version() {
  local current="$1"
  local kind="$2"
  read -r major minor patch <<EOF_VERSION
$(normalize_version "$current")
EOF_VERSION

  case "$kind" in
    major)
      major=$((major + 1))
      minor=0
      patch=0
      ;;
    minor)
      minor=$((minor + 1))
      patch=0
      ;;
    patch|*)
      patch=$((patch + 1))
      ;;
  esac

  printf "v%s.%s.%s\n" "$major" "$minor" "$patch"
}

infer_bump_kind() {
  local message="${1:-}"
  if printf "%s\n" "$message" | grep -Eqi "(^|[[:space:]])BREAKING:"; then
    printf "major\n"
  elif printf "%s\n" "$message" | grep -Eqi "(^|[[:space:]])feat:"; then
    printf "minor\n"
  else
    printf "patch\n"
  fi
}

command_name="${1:-}"
shift || true

case "$command_name" in
  infer-bump)
    infer_bump_kind "${1:-$(cat)}"
    ;;
  current)
    env_file=".env"
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --env-file)
          env_file="$2"
          shift 2
          ;;
        *)
          usage
          exit 1
          ;;
      esac
    done
    read_env_value "$env_file" CURRENT_VERSION || read_env_value "$env_file" FT_APP_VERSION || printf "v0.0.0\n"
    ;;
  next)
    env_file=".env"
    bump_kind="patch"
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --env-file)
          env_file="$2"
          shift 2
          ;;
        --bump-kind)
          bump_kind="$2"
          shift 2
          ;;
        *)
          usage
          exit 1
          ;;
      esac
    done
    current_version="$(read_env_value "$env_file" CURRENT_VERSION || read_env_value "$env_file" FT_APP_VERSION || printf "v0.0.0")"
    bump_version "$current_version" "$bump_kind"
    ;;
  *)
    usage
    exit 1
    ;;
esac
