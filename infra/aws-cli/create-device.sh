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

AWS_REGION="${AWS_REGION:-us-west-1}"
export AWS_REGION

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <thing-name> [--skip-thing] [--policy <policy-name>]" >&2
  exit 1
fi

THING_NAME="$1"
shift

SKIP_THING="false"
POLICY_NAME="${IOT_POLICY_NAME:-v2x-backend-edge-publish}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-thing) SKIP_THING="true"; shift ;;
    --policy) POLICY_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${HERE}/.secrets/iot/${THING_NAME}"
mkdir -p "${SECRETS_DIR}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

if ! aws iot get-policy --policy-name "${POLICY_NAME}" >/dev/null 2>&1; then
  echo "IoT policy not found: ${POLICY_NAME}" >&2
  echo "Create it first (run ./provision.sh) or pass an existing policy name via --policy." >&2
  exit 1
fi

if [[ "${SKIP_THING}" != "true" ]]; then
  if ! aws iot describe-thing --thing-name "${THING_NAME}" >/dev/null 2>&1; then
    aws iot create-thing --thing-name "${THING_NAME}" >/dev/null
  fi
fi

CERT_JSON="$(aws iot create-keys-and-certificate --set-as-active)"
CERT_ARN="$(echo "${CERT_JSON}" | jq -r .certificateArn)"

echo "${CERT_JSON}" | jq -r .certificatePem > "${SECRETS_DIR}/device-cert.pem"
echo "${CERT_JSON}" | jq -r .keyPair.PublicKey > "${SECRETS_DIR}/device-public.key"
echo "${CERT_JSON}" | jq -r .keyPair.PrivateKey > "${SECRETS_DIR}/device-private.key"

aws iot attach-policy --policy-name "${POLICY_NAME}" --target "${CERT_ARN}" >/dev/null
aws iot attach-thing-principal --thing-name "${THING_NAME}" --principal "${CERT_ARN}" >/dev/null

ROOT_CA_URL="https://www.amazontrust.com/repository/AmazonRootCA1.pem"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "${ROOT_CA_URL}" -o "${SECRETS_DIR}/AmazonRootCA1.pem"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "${SECRETS_DIR}/AmazonRootCA1.pem" "${ROOT_CA_URL}"
else
  echo "Note: curl/wget not found; download ${ROOT_CA_URL} to ${SECRETS_DIR}/AmazonRootCA1.pem" >&2
fi

ENDPOINT="$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)"

cat > "${SECRETS_DIR}/device.env" <<ENV
AWS_IOT_ENDPOINT=${ENDPOINT}
AWS_IOT_CLIENT_ID=${THING_NAME}
AWS_IOT_TOPIC=v2x/v1/detections/fleetA/${THING_NAME}
AWS_IOT_CERT=${SECRETS_DIR}/device-cert.pem
AWS_IOT_KEY=${SECRETS_DIR}/device-private.key
AWS_IOT_ROOT_CA=${SECRETS_DIR}/AmazonRootCA1.pem
ENV

echo "Created device credentials in: ${SECRETS_DIR}"
echo "Endpoint: ${ENDPOINT}"
echo "Policy: ${POLICY_NAME}"
echo "Topic example: v2x/v1/detections/fleetA/${THING_NAME}"
