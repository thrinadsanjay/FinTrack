 #!/usr/bin/env bash
set -euo pipefail

required_vars=(
  DEPLOY_PATH
  DEPLOY_REF
  DEPLOY_VERSION
  REQUIREMENTS_CHANGED
  COMPOSE_FILE
  APP_SERVICE
  ENV_FILE
  CONTAINER_CLI
  HEALTH_URL
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required variable: ${var_name}"
    exit 1
  fi
done

if [[ ! -d "${DEPLOY_PATH}" ]]; then
  echo "Deploy path does not exist: ${DEPLOY_PATH}"
  exit 1
fi

cd "${DEPLOY_PATH}"

if [[ ! -d ".git" ]]; then
  echo "Deploy path is not a git repository: ${DEPLOY_PATH}"
  exit 1
fi

echo "Fetching latest refs and tags..."
git fetch --all --tags --prune

if ! git rev-parse --verify "${DEPLOY_REF}^{commit}" >/dev/null 2>&1; then
  echo "Ref not found locally, fetching from origin: ${DEPLOY_REF}"
  git fetch origin "${DEPLOY_REF}"
fi

echo "Checking out deploy ref: ${DEPLOY_REF}"
git checkout --detach "${DEPLOY_REF}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Env file not found, creating: ${ENV_FILE}"
  touch "${ENV_FILE}"
fi

echo "Setting FT_APP_VERSION=${DEPLOY_VERSION} in ${ENV_FILE}"
if grep -q '^FT_APP_VERSION=' "${ENV_FILE}"; then
  sed -i -E "s/^FT_APP_VERSION=.*/FT_APP_VERSION=${DEPLOY_VERSION}/" "${ENV_FILE}"
else
  printf '\nFT_APP_VERSION=%s\n' "${DEPLOY_VERSION}" >> "${ENV_FILE}"
fi

echo "${DEPLOY_VERSION}" > .deploy_version

if [[ "${REQUIREMENTS_CHANGED}" == "true" || "${FORCE_REBUILD:-false}" == "true" ]]; then
  echo "requirements change detected (or force rebuild), rebuilding ${APP_SERVICE} image..."
  "${CONTAINER_CLI}" compose -f "${COMPOSE_FILE}" build "${APP_SERVICE}"
else
  echo "No requirements change detected, skipping image rebuild."
fi

echo "Recreating app service: ${APP_SERVICE}"
"${CONTAINER_CLI}" compose -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate "${APP_SERVICE}"

echo "Running health check: ${HEALTH_URL}"
attempts=10
sleep_seconds=6
health_ok="false"

for ((i=1; i<=attempts; i++)); do
  if health_payload="$(curl -fsS "${HEALTH_URL}")"; then
    echo "Health check passed on attempt ${i}/${attempts}: ${health_payload}"
    health_ok="true"
    break
  fi
  echo "Health check failed on attempt ${i}/${attempts}; retrying in ${sleep_seconds}s..."
  sleep "${sleep_seconds}"
done

if [[ "${health_ok}" != "true" ]]; then
  echo "Health check failed after ${attempts} attempts."
  exit 1
fi

echo "Deployment completed successfully."
