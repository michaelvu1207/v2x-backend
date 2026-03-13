#!/usr/bin/env bash
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1" >&2
    exit 1
  }
}

need aws
need jq

AWS_PROFILE="${AWS_PROFILE:-}"
LIGHTSAIL_REGION="${LIGHTSAIL_REGION:-us-west-2}"
INSTANCE_NAME="${INSTANCE_NAME:-v2x-viewer}"
AVAILABILITY_ZONE="${AVAILABILITY_ZONE:-us-west-2a}"
BLUEPRINT_ID="${BLUEPRINT_ID:-ubuntu_22_04}"
BUNDLE_ID="${BUNDLE_ID:-nano_3_0}"
API_BASE_URL="${API_BASE_URL:-}"
RECREATE="${RECREATE:-false}" # set true to delete/recreate the instance to re-apply user-data

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
INDEX_HTML="${ROOT}/apps/v2x-viewer/public/index.html"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

EXISTS="false"
if aws "${AWS_ARGS[@]}" lightsail get-instances --query "instances[?name==\`${INSTANCE_NAME}\`]" --output json | jq -e 'length>0' >/dev/null; then
  EXISTS="true"
fi

if [[ "${EXISTS}" == "true" && "${RECREATE}" == "true" ]]; then
  echo "Deleting existing instance to re-apply user-data: ${INSTANCE_NAME}"
  aws "${AWS_ARGS[@]}" lightsail delete-instance --instance-name "${INSTANCE_NAME}" >/dev/null
  for _ in $(seq 1 60); do
    if ! aws "${AWS_ARGS[@]}" lightsail get-instances --query "instances[?name==\`${INSTANCE_NAME}\`]" --output json | jq -e 'length>0' >/dev/null; then
      break
    fi
    sleep 5
  done
  EXISTS="false"
fi

if [[ "${EXISTS}" != "true" ]]; then
  echo "Creating Lightsail instance: ${INSTANCE_NAME} (${LIGHTSAIL_REGION}/${AVAILABILITY_ZONE})"

  USERDATA="${WORKDIR}/user-data.sh"
  {
    echo '#!/usr/bin/env bash'
    echo 'set -euo pipefail'
    echo 'export DEBIAN_FRONTEND=noninteractive'
    echo 'apt-get update -y'
    echo 'apt-get install -y nginx'
    echo 'systemctl enable --now nginx'
    echo "cat > /var/www/html/config.json <<'JSON'"
    cat <<JSON
{
  "apiBaseUrl": "${API_BASE_URL}",
  "routes": {
    "recent": "/detections/recent",
    "byObject": "/detections/object/{object_id}",
    "byGeohash": "/detections/geohash/{geohash}"
  }
}
JSON
    echo 'JSON'
    echo "cat > /var/www/html/index.html <<'HTML'"
    cat "${INDEX_HTML}"
    echo 'HTML'
    echo 'nginx -t'
    echo 'systemctl reload nginx'
  } > "${USERDATA}"

  USERDATA_BYTES="$(wc -c < "${USERDATA}" | tr -d ' ')"
  if [[ "${USERDATA_BYTES}" -gt 16000 ]]; then
    echo "User-data too large (${USERDATA_BYTES} bytes). Reduce apps/v2x-viewer/public/index.html or host it elsewhere." >&2
    exit 1
  fi

  aws "${AWS_ARGS[@]}" lightsail create-instances \
    --instance-names "${INSTANCE_NAME}" \
    --availability-zone "${AVAILABILITY_ZONE}" \
    --blueprint-id "${BLUEPRINT_ID}" \
    --bundle-id "${BUNDLE_ID}" \
    --user-data "$(cat "${USERDATA}")" >/dev/null
fi

echo "Waiting for instance to be running and have a public IP..."
PUB_IP=""
for _ in $(seq 1 60); do
  STATE="$(aws "${AWS_ARGS[@]}" lightsail get-instance --instance-name "${INSTANCE_NAME}" --query 'instance.state.name' --output text 2>/dev/null || true)"
  PUB_IP="$(aws "${AWS_ARGS[@]}" lightsail get-instance --instance-name "${INSTANCE_NAME}" --query 'instance.publicIpAddress' --output text 2>/dev/null || true)"
  if [[ "${STATE}" == "running" && -n "${PUB_IP}" && "${PUB_IP}" != "None" ]]; then
    break
  fi
  sleep 5
done

if [[ -z "${PUB_IP}" || "${PUB_IP}" == "None" ]]; then
  echo "Failed to obtain public IP for instance ${INSTANCE_NAME}." >&2
  exit 1
fi

echo "Opening port 80..."
aws "${AWS_ARGS[@]}" lightsail open-instance-public-ports \
  --instance-name "${INSTANCE_NAME}" \
  --port-info fromPort=80,toPort=80,protocol=TCP >/dev/null || true

echo "Deployed: http://${PUB_IP}/"
