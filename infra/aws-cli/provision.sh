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
LAMBDA_NAME="${LAMBDA_NAME:-v2x-backend-ingest}"
RULE_NAME="${RULE_NAME:-v2x_backend_detections_to_ddb}"
IOT_POLICY_NAME="${IOT_POLICY_NAME:-v2x-backend-edge-publish}"
THING_NAME="${THING_NAME:-edge-device-001}"
TTL_DAYS="${TTL_DAYS:-7}"
SKIP_IAM="${SKIP_IAM:-false}" # set to true if your principal can't call iam:*; provide LAMBDA_ROLE_ARN for first-time setup
LAMBDA_ROLE_ARN="${LAMBDA_ROLE_ARN:-}" # required if SKIP_IAM=true and Lambda doesn't exist
ATTACH_DDB_PUT_POLICY="${ATTACH_DDB_PUT_POLICY:-false}" # if true, adds/updates inline policy on the Lambda role (no new role created)
LAMBDA_ROLE_POLICY_NAME="${LAMBDA_ROLE_POLICY_NAME:-v2x-backend-detections-ddb-put}"

export AWS_REGION

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "Region: ${AWS_REGION}"
echo "Account: ${ACCOUNT_ID}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="${HERE}/.secrets"
mkdir -p "${SECRETS_DIR}"

echo "1) DynamoDB table: ${TABLE_NAME}"
if ! aws dynamodb describe-table --table-name "${TABLE_NAME}" >/dev/null 2>&1; then
  aws dynamodb create-table \
    --table-name "${TABLE_NAME}" \
    --attribute-definitions \
      AttributeName=object_id,AttributeType=S \
      AttributeName=ts_event,AttributeType=S \
      AttributeName=geohash,AttributeType=S \
    --key-schema \
      AttributeName=object_id,KeyType=HASH \
      AttributeName=ts_event,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
      {
        "IndexName":"gsi_geohash_time",
        "KeySchema":[
          {"AttributeName":"geohash","KeyType":"HASH"},
          {"AttributeName":"ts_event","KeyType":"RANGE"}
        ],
        "Projection":{"ProjectionType":"ALL"}
      }
    ]' >/dev/null

  aws dynamodb wait table-exists --table-name "${TABLE_NAME}"
fi

TTL_STATUS="$(aws dynamodb describe-time-to-live --table-name "${TABLE_NAME}" --query 'TimeToLiveDescription.TimeToLiveStatus' --output text 2>/dev/null || echo "UNKNOWN")"
if [[ "${TTL_STATUS}" != "ENABLED" ]]; then
  aws dynamodb update-time-to-live \
    --table-name "${TABLE_NAME}" \
    --time-to-live-specification Enabled=true,AttributeName=expires_at >/dev/null
fi

echo "3) Lambda function: ${LAMBDA_NAME}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

cat > "${WORKDIR}/index.py" <<'PY'
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

ddb = boto3.resource("dynamodb")
ddb_client = boto3.client("dynamodb")
serializer = TypeSerializer()

TABLE_NAME = os.environ["TABLE_NAME"]
TTL_DAYS = int(os.environ.get("TTL_DAYS", "7"))

MAX_BATCH = 500
COND_EXPR = "attribute_not_exists(object_id) AND attribute_not_exists(ts_event)"

table = ddb.Table(TABLE_NAME)

class BadRequest(Exception):
    def __init__(self, error: str, message: str = "", extra: dict | None = None):
        super().__init__(message)
        self.error = error
        self.message = message
        self.extra = extra or {}

def _decimalize(value):
    # DynamoDB (boto3) rejects float; convert to Decimal recursively.
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimalize(v) for v in value]
    return value

def _parse_ts(ts: str) -> datetime:
    # expects ISO8601 like 2025-11-13T14:12:01Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)

def _is_http_event(event) -> bool:
    # API Gateway (HTTP API) Lambda proxy payload v2.0 has 'requestContext' and a string 'body'.
    return isinstance(event, dict) and "body" in event and (
        "requestContext" in event or event.get("version") == "2.0" or "rawPath" in event
    )

def _extract_payload(event):
    # Supports 2 ingress shapes:
    # 1) IoT Rule: event is already the JSON payload
    # 2) HTTP API: event contains string body
    if isinstance(event, str):
        event = json.loads(event)

    if _is_http_event(event):
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")
        if not body:
            return {}
        if isinstance(body, str):
            return json.loads(body)
        if isinstance(body, (dict, list)):
            return body
        raise ValueError("Invalid request body")

    return event

def _normalize_payload(payload):
    # Supported request bodies:
    # - single object: {...}
    # - array: [{...}, {...}]
    # - wrapper: { "items": [...] }
    if isinstance(payload, list):
        return True, payload

    if isinstance(payload, dict) and "items" in payload:
        items = payload.get("items")
        if not isinstance(items, list):
            raise BadRequest("bad_request", "Field 'items' must be an array")
        return True, items

    if isinstance(payload, dict):
        return False, [payload]

    raise BadRequest("bad_request", "Payload must be a JSON object or array")

def _serialize_item(item: dict) -> dict:
    return {k: serializer.serialize(v) for k, v in item.items()}

def _http_resp(status: int, body: dict):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }

def _http_bad_request(exc: BadRequest):
    body = {"ok": False, "error": exc.error}
    body.update(exc.extra or {})
    if exc.message:
        body["message"] = exc.message
    return _http_resp(400, body)

def _http_internal_error(exc: Exception):
    return _http_resp(500, {"ok": False, "error": "internal_error", "message": str(exc)})

def handler(event, context):
    is_http = _is_http_event(event)

    try:
        payload = _extract_payload(event)
        is_batch, items = _normalize_payload(payload)
        if len(items) > MAX_BATCH:
            raise BadRequest("too_many_items", extra={"max": MAX_BATCH})
    except BadRequest as e:
        if is_http:
            return _http_bad_request(e)
        raise
    except Exception as e:
        if is_http:
            return _http_resp(400, {"ok": False, "error": "bad_request", "message": str(e)})
        raise

    if not is_batch:
        # Backward compatible single-object mode: keep response shape.
        payload = items[0]
        try:
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object")

            object_id = payload.get("object_id")
            ts = payload.get("timestamp_utc")
            if not object_id or not ts:
                raise ValueError("Missing required fields: object_id, timestamp_utc")

            event_id = payload.get("event_id") or uuid.uuid4().hex
            ts_event = f"{ts}#{event_id}"
            expires_at = int((_parse_ts(ts) + timedelta(days=TTL_DAYS)).timestamp())
        except Exception as e:
            if is_http:
                return _http_resp(400, {"ok": False, "error": "bad_request", "message": str(e)})
            raise

        item = _decimalize(dict(payload))
        item.update(
            {
                "event_id": event_id,
                "object_id": object_id,
                "ts_event": ts_event,
                "expires_at": expires_at,
                "ingested_at_epoch": int(time.time()),
            }
        )

        try:
            table.put_item(Item=item, ConditionExpression=COND_EXPR)
            result = {"ok": True, "object_id": object_id, "ts_event": ts_event}
            return _http_resp(200, result) if is_http else result
        except Exception as e:
            if is_http:
                return _http_internal_error(e)
            raise

    # Batch mode: partial success + per-item results, always HTTP 200 if request parsed.
    now_epoch = int(time.time())
    results_by_index: dict[int, dict] = {}
    prepared: list[dict] = []

    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            results_by_index[idx] = {
                "ok": False,
                "index": idx,
                "error": "bad_item",
                "message": "Item must be a JSON object",
            }
            continue

        object_id = raw.get("object_id")
        ts = raw.get("timestamp_utc")
        if not object_id or not ts:
            results_by_index[idx] = {
                "ok": False,
                "index": idx,
                "error": "bad_item",
                "message": "Missing required fields: object_id, timestamp_utc",
            }
            continue

        event_id = raw.get("event_id") or uuid.uuid4().hex
        ts_event = f"{ts}#{event_id}"

        try:
            expires_at = int((_parse_ts(ts) + timedelta(days=TTL_DAYS)).timestamp())
        except Exception as e:
            results_by_index[idx] = {
                "ok": False,
                "index": idx,
                "error": "bad_item",
                "message": f"Invalid timestamp_utc: {e}",
            }
            continue

        item = _decimalize(dict(raw))
        item.update(
            {
                "event_id": event_id,
                "object_id": object_id,
                "ts_event": ts_event,
                "expires_at": expires_at,
                "ingested_at_epoch": now_epoch,
            }
        )

        prepared.append(
            {
                "index": idx,
                "object_id": object_id,
                "event_id": event_id,
                "ts_event": ts_event,
                "item": item,
            }
        )

    def _mark_ok(p):
        results_by_index[p["index"]] = {
            "ok": True,
            "index": p["index"],
            "object_id": p["object_id"],
            "event_id": p["event_id"],
            "ts_event": p["ts_event"],
        }

    def _mark_err(p, error: str, message: str | None = None):
        r = {
            "ok": False,
            "index": p["index"],
            "error": error,
            "object_id": p["object_id"],
            "event_id": p["event_id"],
            "ts_event": p["ts_event"],
        }
        if message:
            r["message"] = message
        results_by_index[p["index"]] = r

    for i in range(0, len(prepared), 25):
        chunk = prepared[i : i + 25]
        transact_items = [
            {
                "Put": {
                    "TableName": TABLE_NAME,
                    "Item": _serialize_item(p["item"]),
                    "ConditionExpression": COND_EXPR,
                }
            }
            for p in chunk
        ]

        try:
            ddb_client.transact_write_items(TransactItems=transact_items)
            for p in chunk:
                _mark_ok(p)
            continue
        except Exception:
            # Fall back to per-item writes for partial success semantics.
            pass

        for p in chunk:
            try:
                table.put_item(Item=p["item"], ConditionExpression=COND_EXPR)
                _mark_ok(p)
            except ClientError as e:
                code = (e.response.get("Error") or {}).get("Code") or ""
                if code == "ConditionalCheckFailedException":
                    _mark_err(p, "conflict")
                else:
                    _mark_err(p, "internal_error", str(e))
            except Exception as e:
                _mark_err(p, "internal_error", str(e))

    results = [results_by_index.get(i, {"ok": False, "index": i, "error": "internal_error"}) for i in range(len(items))]
    inserted = sum(1 for r in results if r.get("ok") is True)
    failed = len(results) - inserted
    body = {"ok": failed == 0, "inserted": inserted, "failed": failed, "results": results}
    return _http_resp(200, body) if is_http else body
PY

(cd "${WORKDIR}" && zip -q function.zip index.py)

ROLE_ARN=""
EXISTING_ROLE_ARN=""
if aws lambda get-function --function-name "${LAMBDA_NAME}" >/dev/null 2>&1; then
  EXISTING_ROLE_ARN="$(aws lambda get-function --function-name "${LAMBDA_NAME}" --query Configuration.Role --output text)"
fi

if [[ -n "${EXISTING_ROLE_ARN}" ]]; then
  ROLE_ARN="${EXISTING_ROLE_ARN}"
fi

if [[ -z "${ROLE_ARN}" ]]; then
  if [[ "${SKIP_IAM}" == "true" ]]; then
    ROLE_ARN="${LAMBDA_ROLE_ARN}"
    if [[ -z "${ROLE_ARN}" ]]; then
      echo "SKIP_IAM=true but no existing Lambda found and LAMBDA_ROLE_ARN not set." >&2
      echo "Provide an existing role ARN that Lambda can assume and that can write to DynamoDB." >&2
      echo "Example: LAMBDA_ROLE_ARN=arn:aws:iam::${ACCOUNT_ID}:role/<existing-role>" >&2
      exit 1
    fi
  else
    echo "2) IAM role for Lambda"
    ROLE_NAME="${LAMBDA_NAME}-role"

    if ! aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
      cat > "${SECRETS_DIR}/lambda-trust.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
JSON

      aws iam create-role \
        --role-name "${ROLE_NAME}" \
        --assume-role-policy-document "file://${SECRETS_DIR}/lambda-trust.json" >/dev/null

      aws iam attach-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null
    fi

    cat > "${SECRETS_DIR}/lambda-ddb-policy.json" <<JSON
{
  "Version":"2012-10-17",
  "Statement":[{
    "Effect":"Allow",
    "Action":[ "dynamodb:PutItem", "dynamodb:TransactWriteItems" ],
    "Resource":[
      "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    ]
  }]
}
JSON

    aws iam put-role-policy \
      --role-name "${ROLE_NAME}" \
      --policy-name "${LAMBDA_NAME}-ddb-put" \
      --policy-document "file://${SECRETS_DIR}/lambda-ddb-policy.json" >/dev/null

    ROLE_ARN="$(aws iam get-role --role-name "${ROLE_NAME}" --query Role.Arn --output text)"
  fi
fi

if [[ "${ATTACH_DDB_PUT_POLICY}" == "true" ]]; then
  ROLE_NAME_FROM_ARN="${ROLE_ARN##*/}"
  cat > "${SECRETS_DIR}/lambda-ddb-put-inline.json" <<JSON
{
  "Version":"2012-10-17",
  "Statement":[{
    "Effect":"Allow",
    "Action":[ "dynamodb:PutItem", "dynamodb:TransactWriteItems" ],
    "Resource":[
      "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"
    ]
  }]
}
JSON
  aws iam put-role-policy \
    --role-name "${ROLE_NAME_FROM_ARN}" \
    --policy-name "${LAMBDA_ROLE_POLICY_NAME}" \
    --policy-document "file://${SECRETS_DIR}/lambda-ddb-put-inline.json" >/dev/null || true
fi

if ! aws lambda get-function --function-name "${LAMBDA_NAME}" >/dev/null 2>&1; then
  aws lambda create-function \
    --function-name "${LAMBDA_NAME}" \
    --runtime python3.12 \
    --handler index.handler \
    --role "${ROLE_ARN}" \
    --timeout 30 \
    --environment "Variables={TABLE_NAME=${TABLE_NAME},TTL_DAYS=${TTL_DAYS}}" \
    --zip-file "fileb://${WORKDIR}/function.zip" >/dev/null
else
  aws lambda update-function-code \
    --function-name "${LAMBDA_NAME}" \
    --zip-file "fileb://${WORKDIR}/function.zip" >/dev/null

  ENV_ARG="Variables={TABLE_NAME=${TABLE_NAME},TTL_DAYS=${TTL_DAYS}}"
  if [[ "${ATTACH_DDB_PUT_POLICY}" == "true" ]]; then
    # Force new execution env so it picks up fresh role credentials after policy updates.
    ENV_ARG="Variables={TABLE_NAME=${TABLE_NAME},TTL_DAYS=${TTL_DAYS},POLICY_REFRESH=$(date +%s)}"
  fi

  aws lambda update-function-configuration \
    --function-name "${LAMBDA_NAME}" \
    --timeout 30 \
    --environment "${ENV_ARG}" >/dev/null || {
      aws lambda wait function-updated --function-name "${LAMBDA_NAME}"
      aws lambda update-function-configuration \
        --function-name "${LAMBDA_NAME}" \
        --timeout 30 \
        --environment "${ENV_ARG}" >/dev/null
    }
fi

LAMBDA_ARN="$(aws lambda get-function --function-name "${LAMBDA_NAME}" --query Configuration.FunctionArn --output text)"

echo "4) IoT Topic Rule: ${RULE_NAME}"
cat > "${SECRETS_DIR}/iot-rule.json" <<JSON
{
  "sql": "SELECT *, topic(5) AS device_id FROM 'v2x/v1/detections/+/+'",
  "awsIotSqlVersion": "2016-03-23",
  "actions": [{ "lambda": { "functionArn": "${LAMBDA_ARN}" } }],
  "ruleDisabled": false
}
JSON

if ! aws iot get-topic-rule --rule-name "${RULE_NAME}" >/dev/null 2>&1; then
  aws iot create-topic-rule \
    --rule-name "${RULE_NAME}" \
    --topic-rule-payload "file://${SECRETS_DIR}/iot-rule.json" >/dev/null
else
  aws iot replace-topic-rule \
    --rule-name "${RULE_NAME}" \
    --topic-rule-payload "file://${SECRETS_DIR}/iot-rule.json" >/dev/null
fi

STATEMENT_ID="iot-${RULE_NAME}"
if ! aws lambda get-policy --function-name "${LAMBDA_NAME}" >/dev/null 2>&1 || \
   ! aws lambda get-policy --function-name "${LAMBDA_NAME}" | jq -e --arg s "${STATEMENT_ID}" '.Policy|fromjson|.Statement[]|select(.Sid==$s)' >/dev/null 2>&1; then
  aws lambda add-permission \
    --function-name "${LAMBDA_NAME}" \
    --statement-id "${STATEMENT_ID}" \
    --action "lambda:InvokeFunction" \
    --principal iot.amazonaws.com \
    --source-arn "arn:aws:iot:${AWS_REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" >/dev/null
fi

echo "5) IoT policy + initial device (Thing + cert): ${THING_NAME}"
cat > "${SECRETS_DIR}/iot-policy.json" <<JSON
{
  "Version":"2012-10-17",
  "Statement":[
    {
      "Effect":"Allow",
      "Action":[ "iot:Connect" ],
      "Resource":[ "arn:aws:iot:${AWS_REGION}:${ACCOUNT_ID}:client/\${iot:Connection.Thing.ThingName}" ]
    },
    {
      "Effect":"Allow",
      "Action":[ "iot:Publish" ],
      "Resource":[ "arn:aws:iot:${AWS_REGION}:${ACCOUNT_ID}:topic/v2x/v1/detections/*/\${iot:Connection.Thing.ThingName}" ]
    }
  ]
}
JSON

if ! aws iot get-policy --policy-name "${IOT_POLICY_NAME}" >/dev/null 2>&1; then
  aws iot create-policy --policy-name "${IOT_POLICY_NAME}" --policy-document "file://${SECRETS_DIR}/iot-policy.json" >/dev/null
fi

if ! aws iot describe-thing --thing-name "${THING_NAME}" >/dev/null 2>&1; then
  aws iot create-thing --thing-name "${THING_NAME}" >/dev/null
fi

EXISTING_THING_PRINCIPALS="$(aws iot list-thing-principals --thing-name "${THING_NAME}" --query principals --output text 2>/dev/null || true)"
if [[ -z "${EXISTING_THING_PRINCIPALS}" || "${EXISTING_THING_PRINCIPALS}" == "None" ]]; then
  "${HERE}/create-device.sh" "${THING_NAME}" --skip-thing --policy "${IOT_POLICY_NAME}"
else
  echo "Thing already has certificate(s) attached; skipping cert creation."
fi

ENDPOINT="$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)"
echo "Done."
echo "IoT data endpoint: ${ENDPOINT}"
echo "DynamoDB table: ${TABLE_NAME}"
echo "Lambda: ${LAMBDA_NAME}"
echo "IoT rule: ${RULE_NAME}"
