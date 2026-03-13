#!/usr/bin/env bash
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing dependency: $1" >&2
    exit 1
  }
}

need aws

AWS_REGION="${AWS_REGION:-us-west-1}"
export AWS_REGION

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_FILE="${PAYLOAD_FILE:-${HERE}/payload.sample.json}"
TOPIC="${TOPIC:-v2x/v1/detections/fleetA/edge-device-001}"

ENDPOINT="$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)"

aws iot-data publish \
  --endpoint-url "https://${ENDPOINT}" \
  --topic "${TOPIC}" \
  --cli-binary-format raw-in-base64-out \
  --payload "fileb://${PAYLOAD_FILE}"

echo "Published to ${TOPIC}"

