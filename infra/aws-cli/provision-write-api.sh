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
INGEST_LAMBDA_NAME="${INGEST_LAMBDA_NAME:-v2x-backend-ingest}"
API_NAME="${API_NAME:-v2x-backend-api}"
STAGE_NAME="${STAGE_NAME:-\$default}"

export AWS_REGION

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "Region: ${AWS_REGION}"
echo "Account: ${ACCOUNT_ID}"

INGEST_LAMBDA_ARN="$(aws lambda get-function --function-name "${INGEST_LAMBDA_NAME}" --query Configuration.FunctionArn --output text)"

API_ID=""
EXISTING="$(aws apigatewayv2 get-apis --query 'Items[?Name==`'"${API_NAME}"'`].ApiId' --output text)"
if [[ -n "${EXISTING}" && "${EXISTING}" != "None" ]]; then
  API_ID="${EXISTING}"
else
  API_ID="$(aws apigatewayv2 create-api \
    --name "${API_NAME}" \
    --protocol-type HTTP \
    --cors-configuration AllowOrigins='*',AllowMethods='GET,POST,OPTIONS',AllowHeaders='content-type' \
    --query ApiId --output text)"
fi

# Ensure CORS includes POST (and doesn't break existing GET routes).
aws apigatewayv2 update-api \
  --api-id "${API_ID}" \
  --cors-configuration AllowOrigins='*',AllowMethods='GET,POST,OPTIONS',AllowHeaders='content-type' >/dev/null

INTEGRATION_ID="$(aws apigatewayv2 create-integration \
  --api-id "${API_ID}" \
  --integration-type AWS_PROXY \
  --integration-uri "${INGEST_LAMBDA_ARN}" \
  --payload-format-version "2.0" \
  --query IntegrationId --output text)"

if ! aws apigatewayv2 get-routes --api-id "${API_ID}" --query "Items[?RouteKey==\`POST /detections\`]" --output json | jq -e 'length>0' >/dev/null 2>&1; then
  aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "POST /detections" --target "integrations/${INTEGRATION_ID}" >/dev/null
fi

if [[ "${STAGE_NAME}" == "\$default" ]]; then
  if ! aws apigatewayv2 get-stage --api-id "${API_ID}" --stage-name "\$default" >/dev/null 2>&1; then
    aws apigatewayv2 create-stage --api-id "${API_ID}" --stage-name "\$default" --auto-deploy >/dev/null
  fi
else
  if ! aws apigatewayv2 get-stage --api-id "${API_ID}" --stage-name "${STAGE_NAME}" >/dev/null 2>&1; then
    aws apigatewayv2 create-stage --api-id "${API_ID}" --stage-name "${STAGE_NAME}" --auto-deploy >/dev/null
  fi
fi

STATEMENT_ID="apigw-write-${API_ID}"
if ! aws lambda get-policy --function-name "${INGEST_LAMBDA_NAME}" >/dev/null 2>&1 || \
   ! aws lambda get-policy --function-name "${INGEST_LAMBDA_NAME}" | jq -e --arg s "${STATEMENT_ID}" '.Policy|fromjson|.Statement[]|select(.Sid==$s)' >/dev/null 2>&1; then
  aws lambda add-permission \
    --function-name "${INGEST_LAMBDA_NAME}" \
    --statement-id "${STATEMENT_ID}" \
    --action "lambda:InvokeFunction" \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" >/dev/null
fi

API_ENDPOINT="$(aws apigatewayv2 get-api --api-id "${API_ID}" --query ApiEndpoint --output text)"

echo "Done."
echo "HTTP API: ${API_ENDPOINT}"
echo "Write endpoint:"
echo "  curl -X POST -H 'content-type: application/json' -d '{\"items\":[{\"object_id\":\"traffic_cone_001\",\"timestamp_utc\":\"2026-02-05T00:00:00Z\"},{\"object_id\":\"traffic_cone_002\",\"timestamp_utc\":\"2026-02-05T00:00:01Z\"}]}' ${API_ENDPOINT}/detections"
