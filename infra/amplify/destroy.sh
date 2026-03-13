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

AWS_REGION="${AWS_REGION:-us-west-2}"
APP_NAME="${APP_NAME:-v2x-backend}"

APP_ID="$(aws amplify list-apps --max-results 100 --query "apps[?name==\`${APP_NAME}\`].appId | [0]" --output text 2>/dev/null || true)"
if [[ -z "${APP_ID}" || "${APP_ID}" == "None" ]]; then
  echo "Amplify app not found: ${APP_NAME}"
  exit 0
fi

aws amplify delete-app --app-id "${APP_ID}" >/dev/null
echo "Deleted Amplify app: ${APP_NAME} (${APP_ID})"
