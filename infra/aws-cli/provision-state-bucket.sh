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

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STATE_BUCKET="${STATE_BUCKET:-v2x-backend-state-${ACCOUNT_ID}-${AWS_REGION}}"
STATE_BASE_URL="https://${STATE_BUCKET}.s3.${AWS_REGION}.amazonaws.com"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

if ! aws s3api head-bucket --bucket "${STATE_BUCKET}" >/dev/null 2>&1; then
  if [[ "${AWS_REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${STATE_BUCKET}" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "${STATE_BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" >/dev/null
  fi
fi

aws s3api put-public-access-block \
  --bucket "${STATE_BUCKET}" \
  --public-access-block-configuration BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false >/dev/null

aws s3api put-bucket-cors \
  --bucket "${STATE_BUCKET}" \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "HEAD"],
      "AllowedOrigins": ["*"],
      "ExposeHeaders": ["ETag", "Content-Length"],
      "MaxAgeSeconds": 3000
    }]
  }' >/dev/null

aws s3api put-bucket-policy \
  --bucket "${STATE_BUCKET}" \
  --policy "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Sid\": \"PublicReadV2XBackendAssets\",
      \"Effect\": \"Allow\",
      \"Principal\": \"*\",
      \"Action\": [\"s3:GetObject\"],
      \"Resource\": [
        \"arn:aws:s3:::${STATE_BUCKET}/api/*\",
        \"arn:aws:s3:::${STATE_BUCKET}/snapshots/*\"
      ]
    }]
  }" >/dev/null

printf '%s' '{"objects":[],"bridge_status":{"status":"disconnected","carla_fps":0,"objects_tracked":0,"cameras_active":0,"last_heartbeat":null},"updated_at":null}' > "${WORKDIR}/state.json"
printf '%s' '{"road_network":[]}' > "${WORKDIR}/map-data.json"

aws s3api put-object \
  --bucket "${STATE_BUCKET}" \
  --key "api/state.json" \
  --content-type "application/json" \
  --cache-control "max-age=2" \
  --body "${WORKDIR}/state.json" >/dev/null

aws s3api put-object \
  --bucket "${STATE_BUCKET}" \
  --key "api/map-data.json" \
  --content-type "application/json" \
  --cache-control "max-age=3600" \
  --body "${WORKDIR}/map-data.json" >/dev/null

echo "Done."
echo "State bucket: ${STATE_BUCKET}"
echo "State base URL: ${STATE_BASE_URL}"
