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
need zip

AWS_REGION="${AWS_REGION:-us-west-1}"
TABLE_NAME="${TABLE_NAME:-v2x-backend-detections}"
INGEST_LAMBDA_NAME="${INGEST_LAMBDA_NAME:-v2x-backend-ingest}"
READ_LAMBDA_NAME="${READ_LAMBDA_NAME:-v2x-backend-read}"
API_NAME="${API_NAME:-v2x-backend-api}"
STAGE_NAME="${STAGE_NAME:-\$default}"
ATTACH_DDB_READ_POLICY="${ATTACH_DDB_READ_POLICY:-true}"
READ_POLICY_NAME="${READ_POLICY_NAME:-v2x-backend-detections-ddb-read}"
VIDEO_AWS_REGION="${VIDEO_AWS_REGION:-us-west-2}"
VIDEO_STREAM_PREFIX="${VIDEO_STREAM_PREFIX:-v2x-backend-cam-}"
VIDEO_HLS_EXPIRES_SECONDS="${VIDEO_HLS_EXPIRES_SECONDS:-300}"

export AWS_REGION

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "Region: ${AWS_REGION}"
echo "Account: ${ACCOUNT_ID}"

ROLE_ARN="$(aws lambda get-function --function-name "${INGEST_LAMBDA_NAME}" --query Configuration.Role --output text)"
ROLE_NAME="${ROLE_ARN##*/}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${HERE}/.secrets"
mkdir -p "${SECRETS_DIR}"

if [[ "${ATTACH_DDB_READ_POLICY}" == "true" ]]; then
  cat > "${SECRETS_DIR}/lambda-ddb-read-inline.json" <<JSON
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Effect":"Allow",
      "Action":[ "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan" ],
      "Resource":[
        "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}",
        "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}/index/*"
      ]
    },
    {
      "Effect":"Allow",
      "Action":[
        "kinesisvideo:DescribeStream",
        "kinesisvideo:GetDataEndpoint"
      ],
      "Resource":[
        "arn:aws:kinesisvideo:${VIDEO_AWS_REGION}:${ACCOUNT_ID}:stream/${VIDEO_STREAM_PREFIX}*"
      ]
    },
    {
      "Effect":"Allow",
      "Action":[
        "kinesisvideo:GetHLSStreamingSessionURL"
      ],
      "Resource":"*"
    }
  ]
}
JSON
  aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${READ_POLICY_NAME}" \
    --policy-document "file://${SECRETS_DIR}/lambda-ddb-read-inline.json" >/dev/null || true
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

cat > "${WORKDIR}/index.py" <<PY
import base64
import json
import os
from decimal import Decimal
from botocore.config import Config as BotoConfig

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "${TABLE_NAME}")
GSI_NAME = os.environ.get("GSI_NAME", "gsi_geohash_time")
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "200"))
VIDEO_AWS_REGION = os.environ.get("VIDEO_AWS_REGION", "${VIDEO_AWS_REGION}")
VIDEO_STREAM_PREFIX = os.environ.get("VIDEO_STREAM_PREFIX", "${VIDEO_STREAM_PREFIX}")
VIDEO_HLS_EXPIRES_SECONDS = int(os.environ.get("VIDEO_HLS_EXPIRES_SECONDS", "${VIDEO_HLS_EXPIRES_SECONDS}"))

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
video_client = boto3.client("kinesisvideo", region_name=VIDEO_AWS_REGION, config=BotoConfig(retries={"max_attempts": 3}))

ALLOWED_CAMERA_IDS = {"ch1", "ch2", "ch3", "ch4"}

def _jsonable(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value

def _strip_api_fields(item):
    # Keep storage as-is, but remove fleet identifiers from the public read API.
    if not isinstance(item, dict):
        return item
    item = dict(item)
    item.pop("fleet_id", None)
    return item

def _b64(obj):
    if obj is None:
        return None
    return base64.urlsafe_b64encode(json.dumps(obj).encode("utf-8")).decode("utf-8")

def _unb64(s):
    if not s:
        return None
    return json.loads(base64.urlsafe_b64decode(s.encode("utf-8")).decode("utf-8"))

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(body),
    }

def _camera_stream_name(camera_id):
    return f"{VIDEO_STREAM_PREFIX}{camera_id}"

def _get_hls_session(camera_id):
    if camera_id not in ALLOWED_CAMERA_IDS:
        return _resp(404, {"error": "camera_not_found", "cameraId": camera_id})

    stream_name = _camera_stream_name(camera_id)

    try:
        endpoint = video_client.get_data_endpoint(
            StreamName=stream_name,
            APIName="GET_HLS_STREAMING_SESSION_URL",
        )["DataEndpoint"]
        archived_media = boto3.client(
            "kinesis-video-archived-media",
            region_name=VIDEO_AWS_REGION,
            endpoint_url=endpoint,
            config=BotoConfig(retries={"max_attempts": 3}),
        )
        hls_url = archived_media.get_hls_streaming_session_url(
            StreamName=stream_name,
            PlaybackMode="LIVE",
            Expires=VIDEO_HLS_EXPIRES_SECONDS,
            ContainerFormat="FRAGMENTED_MP4",
            DiscontinuityMode="ALWAYS",
            DisplayFragmentTimestamp="ALWAYS",
            MaxMediaPlaylistFragmentResults=5,
        )["HLSStreamingSessionURL"]
        return _resp(
            200,
            {
                "cameraId": camera_id,
                "streamName": stream_name,
                "playbackMode": "LIVE",
                "hlsUrl": hls_url,
                "expiresIn": VIDEO_HLS_EXPIRES_SECONDS,
                "region": VIDEO_AWS_REGION,
            },
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        status = 404 if error_code in {"ResourceNotFoundException", "NoDataRetentionException"} else 502
        return _resp(
            status,
            {
                "error": "video_session_unavailable",
                "cameraId": camera_id,
                "streamName": stream_name,
                "detail": error_code,
            },
        )

def handler(event, context):
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    qs = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}

    try:
        limit = int(qs.get("limit") or "50")
    except ValueError:
        limit = 50
    limit = max(1, min(MAX_LIMIT, limit))

    next_token = qs.get("next")
    exclusive_start_key = _unb64(next_token)

    if path.startswith("/video/session/"):
        camera_id = path_params.get("camera_id") or path.split("/video/session/", 1)[1]
        return _get_hls_session(camera_id)

    if path.startswith("/detections/object/"):
        object_id = path_params.get("object_id") or path.split("/detections/object/", 1)[1]
        kwargs = {
            "KeyConditionExpression": Key("object_id").eq(object_id),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        resp = table.query(**kwargs)
        items = [_strip_api_fields(x) for x in (resp.get("Items", []) or [])]
        return _resp(
            200,
            {
                "items": _jsonable(items),
                "next": _b64(resp.get("LastEvaluatedKey")),
            },
        )

    if path.startswith("/detections/geohash/"):
        geohash = path_params.get("geohash") or path.split("/detections/geohash/", 1)[1]
        kwargs = {
            "IndexName": GSI_NAME,
            "KeyConditionExpression": Key("geohash").eq(geohash),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        resp = table.query(**kwargs)
        items = [_strip_api_fields(x) for x in (resp.get("Items", []) or [])]
        return _resp(
            200,
            {
                "items": _jsonable(items),
                "next": _b64(resp.get("LastEvaluatedKey")),
            },
        )

    if path == "/detections/recent":
        # NOTE: DynamoDB has no global "recent" query without a dedicated index.
        # This is a best-effort scan for small tables; sort client-side.
        kwargs = {"Limit": limit}
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        resp = table.scan(**kwargs)
        items = [_strip_api_fields(x) for x in (resp.get("Items", []) or [])]
        items = sorted(items, key=lambda x: (x.get("timestamp_utc") or ""), reverse=True)
        return _resp(
            200,
            {
                "items": _jsonable(items),
                "next": _b64(resp.get("LastEvaluatedKey")),
            },
        )

    if path in ("", "/"):
        return _resp(
            200,
            {
                "ok": True,
                "routes": [
                    "/detections/recent",
                    "/detections/object/{object_id}",
                    "/detections/geohash/{geohash}",
                    "/video/session/{camera_id}",
                ],
            },
        )

    return _resp(404, {"error": "not_found", "path": path})
PY

(cd "${WORKDIR}" && zip -q function.zip index.py)

if ! aws lambda get-function --function-name "${READ_LAMBDA_NAME}" >/dev/null 2>&1; then
  aws lambda create-function \
    --function-name "${READ_LAMBDA_NAME}" \
    --runtime python3.12 \
    --handler index.handler \
    --role "${ROLE_ARN}" \
    --timeout 10 \
    --environment "Variables={TABLE_NAME=${TABLE_NAME},GSI_NAME=gsi_geohash_time,MAX_LIMIT=200,VIDEO_AWS_REGION=${VIDEO_AWS_REGION},VIDEO_STREAM_PREFIX=${VIDEO_STREAM_PREFIX},VIDEO_HLS_EXPIRES_SECONDS=${VIDEO_HLS_EXPIRES_SECONDS}}" \
    --zip-file "fileb://${WORKDIR}/function.zip" >/dev/null
else
  aws lambda update-function-code \
    --function-name "${READ_LAMBDA_NAME}" \
    --zip-file "fileb://${WORKDIR}/function.zip" >/dev/null

      aws lambda update-function-configuration \
        --function-name "${READ_LAMBDA_NAME}" \
        --timeout 10 \
        --environment "Variables={TABLE_NAME=${TABLE_NAME},GSI_NAME=gsi_geohash_time,MAX_LIMIT=200,VIDEO_AWS_REGION=${VIDEO_AWS_REGION},VIDEO_STREAM_PREFIX=${VIDEO_STREAM_PREFIX},VIDEO_HLS_EXPIRES_SECONDS=${VIDEO_HLS_EXPIRES_SECONDS}}" >/dev/null || {
      aws lambda wait function-updated --function-name "${READ_LAMBDA_NAME}"
      aws lambda update-function-configuration \
        --function-name "${READ_LAMBDA_NAME}" \
        --timeout 10 \
        --environment "Variables={TABLE_NAME=${TABLE_NAME},GSI_NAME=gsi_geohash_time,MAX_LIMIT=200,VIDEO_AWS_REGION=${VIDEO_AWS_REGION},VIDEO_STREAM_PREFIX=${VIDEO_STREAM_PREFIX},VIDEO_HLS_EXPIRES_SECONDS=${VIDEO_HLS_EXPIRES_SECONDS}}" >/dev/null
    }
fi

READ_LAMBDA_ARN="$(aws lambda get-function --function-name "${READ_LAMBDA_NAME}" --query Configuration.FunctionArn --output text)"

API_ID=""
EXISTING="$(aws apigatewayv2 get-apis --query 'Items[?Name==`'"${API_NAME}"'`].ApiId' --output text)"
if [[ -n "${EXISTING}" && "${EXISTING}" != "None" ]]; then
  API_ID="${EXISTING}"
else
  API_ID="$(aws apigatewayv2 create-api \
    --name "${API_NAME}" \
    --protocol-type HTTP \
    --cors-configuration AllowOrigins='*',AllowMethods='GET,OPTIONS',AllowHeaders='content-type' \
    --query ApiId --output text)"
fi

INTEGRATION_ID="$(aws apigatewayv2 create-integration \
  --api-id "${API_ID}" \
  --integration-type AWS_PROXY \
  --integration-uri "${READ_LAMBDA_ARN}" \
  --payload-format-version "2.0" \
  --query IntegrationId --output text)"

aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "GET /detections/recent" --target "integrations/${INTEGRATION_ID}" >/dev/null || true
aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "GET /detections/object/{object_id}" --target "integrations/${INTEGRATION_ID}" >/dev/null || true
aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "GET /detections/geohash/{geohash}" --target "integrations/${INTEGRATION_ID}" >/dev/null || true
aws apigatewayv2 create-route --api-id "${API_ID}" --route-key "GET /video/session/{camera_id}" --target "integrations/${INTEGRATION_ID}" >/dev/null || true

if [[ "${STAGE_NAME}" == "\$default" ]]; then
  aws apigatewayv2 create-stage --api-id "${API_ID}" --stage-name "\$default" --auto-deploy >/dev/null || true
else
  aws apigatewayv2 create-stage --api-id "${API_ID}" --stage-name "${STAGE_NAME}" --auto-deploy >/dev/null || true
fi

STATEMENT_ID="apigw-${API_ID}"
if ! aws lambda get-policy --function-name "${READ_LAMBDA_NAME}" >/dev/null 2>&1 || \
   ! aws lambda get-policy --function-name "${READ_LAMBDA_NAME}" | jq -e --arg s "${STATEMENT_ID}" '.Policy|fromjson|.Statement[]|select(.Sid==$s)' >/dev/null 2>&1; then
  aws lambda add-permission \
    --function-name "${READ_LAMBDA_NAME}" \
    --statement-id "${STATEMENT_ID}" \
    --action "lambda:InvokeFunction" \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" >/dev/null
fi

API_ENDPOINT="$(aws apigatewayv2 get-api --api-id "${API_ID}" --query ApiEndpoint --output text)"

echo "Done."
echo "Read Lambda: ${READ_LAMBDA_NAME}"
echo "HTTP API: ${API_ENDPOINT}"
echo "Example:"
echo "  ${API_ENDPOINT}/detections/object/traffic_cone_001?limit=10"
