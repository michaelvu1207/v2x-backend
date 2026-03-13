#!/usr/bin/env bash
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1" >&2
    exit 1
  }
}

need aws
need docker
need jq

AWS_PROFILE="${AWS_PROFILE:-}"
LIGHTSAIL_REGION="${LIGHTSAIL_REGION:-us-west-2}"
SERVICE_NAME="${SERVICE_NAME:-v2x-viewer}"
CONTAINER_NAME="${CONTAINER_NAME:-viewer}"
CONTAINER_PORT="${CONTAINER_PORT:-3000}"
API_BASE_URL="${API_BASE_URL:-}"

if [[ -z "${API_BASE_URL}" ]]; then
  echo "API_BASE_URL is required (from provision-read-api.sh output)." >&2
  exit 1
fi

AWS_ARGS=()
if [[ -n "${AWS_PROFILE}" ]]; then
  AWS_ARGS+=(--profile "${AWS_PROFILE}")
fi

AWS_ARGS+=(--region "${LIGHTSAIL_REGION}")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${ROOT}/apps/v2x-viewer"

echo "Building container image..."
docker build -t "${SERVICE_NAME}:local" "${APP_DIR}" >/dev/null

echo "Ensuring Lightsail container service exists: ${SERVICE_NAME} (${LIGHTSAIL_REGION})"
if ! aws "${AWS_ARGS[@]}" lightsail get-container-services --query "containerServices[?containerServiceName==\`${SERVICE_NAME}\`]" --output json | jq -e 'length>0' >/dev/null; then
  aws "${AWS_ARGS[@]}" lightsail create-container-service \
    --service-name "${SERVICE_NAME}" \
    --power nano \
    --scale 1 >/dev/null
fi

echo "Pushing image to Lightsail..."
PUSH_JSON="$(aws "${AWS_ARGS[@]}" lightsail push-container-image \
  --service-name "${SERVICE_NAME}" \
  --label "${SERVICE_NAME}" \
  --image "${SERVICE_NAME}:local")"

IMAGE_REF="$(echo "${PUSH_JSON}" | jq -r '.image.image')"
if [[ -z "${IMAGE_REF}" || "${IMAGE_REF}" == "null" ]]; then
  echo "Failed to push image (no image ref returned)." >&2
  echo "${PUSH_JSON}" | jq . >&2 || true
  exit 1
fi

echo "Deploying..."
cat > /tmp/lightsail-deploy.json <<JSON
{
  "containers": {
    "${CONTAINER_NAME}": {
      "image": "${IMAGE_REF}",
      "environment": {
        "API_BASE_URL": "${API_BASE_URL}",
        "PORT": "${CONTAINER_PORT}"
      },
      "ports": {
        "${CONTAINER_PORT}": "HTTP"
      }
    }
  },
  "publicEndpoint": {
    "containerName": "${CONTAINER_NAME}",
    "containerPort": ${CONTAINER_PORT},
    "healthCheck": {
      "path": "/healthz",
      "successCodes": "200-399",
      "intervalSeconds": 10,
      "timeoutSeconds": 5,
      "healthyThreshold": 2,
      "unhealthyThreshold": 2
    }
  }
}
JSON

aws "${AWS_ARGS[@]}" lightsail create-container-service-deployment \
  --service-name "${SERVICE_NAME}" \
  --cli-input-json file:///tmp/lightsail-deploy.json >/dev/null

echo "Waiting for service URL..."
for _ in $(seq 1 30); do
  URL="$(aws "${AWS_ARGS[@]}" lightsail get-container-services --service-name "${SERVICE_NAME}" --query 'containerServices[0].url' --output text 2>/dev/null || true)"
  STATE="$(aws "${AWS_ARGS[@]}" lightsail get-container-services --service-name "${SERVICE_NAME}" --query 'containerServices[0].currentDeployment.state' --output text 2>/dev/null || true)"
  if [[ -n "${URL}" && "${URL}" != "None" && "${STATE}" == "ACTIVE" ]]; then
    echo "Deployed: ${URL}"
    exit 0
  fi
  sleep 5
done

echo "Deployment started, but URL/state not ready yet." >&2
aws "${AWS_ARGS[@]}" lightsail get-container-services --service-name "${SERVICE_NAME}" --output json | jq . >&2 || true
exit 1

