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
STREAM_PREFIX="${STREAM_PREFIX:-v2x-backend-cam-}"
RETENTION_HOURS="${RETENTION_HOURS:-24}"
CAMERAS="${CAMERAS:-ch1 ch2 ch3 ch4}"

export AWS_REGION

for camera_id in ${CAMERAS}; do
  stream_name="${STREAM_PREFIX}${camera_id}"
  if ! aws kinesisvideo describe-stream --stream-name "${stream_name}" >/dev/null 2>&1; then
    aws kinesisvideo create-stream \
      --stream-name "${stream_name}" \
      --data-retention-in-hours "${RETENTION_HOURS}" >/dev/null
  fi

  current_retention="$(aws kinesisvideo describe-stream --stream-name "${stream_name}" --query 'StreamInfo.DataRetentionInHours' --output text)"
  current_version="$(aws kinesisvideo describe-stream --stream-name "${stream_name}" --query 'StreamInfo.Version' --output text)"
  if [[ "${current_retention}" -lt "${RETENTION_HOURS}" ]]; then
    aws kinesisvideo update-data-retention \
      --stream-name "${stream_name}" \
      --current-version "${current_version}" \
      --operation INCREASE_DATA_RETENTION \
      --data-retention-change-in-hours "$((RETENTION_HOURS - current_retention))" >/dev/null
  fi

  aws kinesisvideo describe-stream --stream-name "${stream_name}" \
    --query 'StreamInfo.{Name:StreamName,ARN:StreamARN,Status:Status,Retention:DataRetentionInHours}' \
    --output json
done
