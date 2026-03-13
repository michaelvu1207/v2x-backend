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
SERVICE_NAME="${SERVICE_NAME:-v2x-viewer}"

AWS_ARGS=()
if [[ -n "${AWS_PROFILE}" ]]; then
  AWS_ARGS+=(--profile "${AWS_PROFILE}")
fi
AWS_ARGS+=(--region "${LIGHTSAIL_REGION}")

if aws "${AWS_ARGS[@]}" lightsail get-container-services --query "containerServices[?containerServiceName==\`${SERVICE_NAME}\`]" --output json | jq -e 'length>0' >/dev/null; then
  aws "${AWS_ARGS[@]}" lightsail delete-container-service --service-name "${SERVICE_NAME}" >/dev/null
  echo "Deleted container service: ${SERVICE_NAME}"
else
  echo "Container service not found: ${SERVICE_NAME}"
fi

