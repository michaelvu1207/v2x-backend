# AGENTS.md

## Repo layout
- `apps/v2x-viewer`: Express-based viewer UI (Node 20+).
- `apps/v2x-viewer-static`: Static viewer + docs pages (used by Amplify hosting).
- `infra/aws-cli`: AWS CLI scripts for IoT Core → Lambda → DynamoDB + API Gateway.
- `infra/lightsail`: Deploy viewer to Lightsail.
- `infra/amplify`: Deploy static viewer + docs to Amplify Hosting.

## App commands

### Viewer (apps/v2x-viewer)
```bash
cd apps/v2x-viewer
npm install
npm run dev
```

Run the server without dev tooling:
```bash
cd apps/v2x-viewer
npm start
```

Quick health check:
```bash
curl http://localhost:3000/healthz
```

Viewer config (optional env vars):
- `API_BASE_URL` (defaults to the existing read API in `us-west-1`)
- `PORT` (defaults to `3000`)

### Static viewer (apps/v2x-viewer-static)
Local preview (manual static hosting):
```bash
cd apps/v2x-viewer-static
cat > config.json <<'JSON'
{
  "apiBaseUrl": "https://<api-id>.execute-api.us-west-1.amazonaws.com",
  "routes": {
    "recent": "/detections/recent",
    "byObject": "/detections/object/{object_id}",
    "byGeohash": "/detections/geohash/{geohash}"
  }
}
JSON
python3 -m http.server 4173
```
Open `http://localhost:4173/`.

## Infra workflows

### IoT ingest pipeline (infra/aws-cli)
Prereqs: AWS CLI v2 authenticated, `jq`, `zip`.

Provision pipeline in `us-west-1`:
```bash
cd infra/aws-cli
export AWS_PROFILE="your-profile"  # optional
export AWS_REGION="us-west-1"       # optional
./provision.sh
```
Optional env vars: `TABLE_NAME` (default `v2x_detections`), `LAMBDA_NAME` (default `v2x-detections-ingest`), `RULE_NAME` (default `v2x_detections_to_ddb`), `IOT_POLICY_NAME` (default `v2x-edge-publish`), `THING_NAME` (default `edge-device-001`), `TTL_DAYS` (default `7`), `SKIP_IAM` (default `false`), `LAMBDA_ROLE_ARN` (required when `SKIP_IAM=true` and Lambda does not already exist), `ATTACH_DDB_PUT_POLICY` (default `false`), `LAMBDA_ROLE_POLICY_NAME` (default `v2x-detections-ddb-put`).

If IAM role creation is blocked, reuse an existing Lambda role:
```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 SKIP_IAM=true \
  LAMBDA_ROLE_ARN="arn:aws:iam::<account-id>:role/<existing-role>" \
  ./provision.sh
```

Optionally let the script attach DynamoDB PutItem permissions to that existing role:
```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 SKIP_IAM=true \
  LAMBDA_ROLE_ARN="arn:aws:iam::<account-id>:role/<existing-role>" \
  ATTACH_DDB_PUT_POLICY=true \
  ./provision.sh
```

Create another device cert:
```bash
cd infra/aws-cli
./create-device.sh edge-device-002
```
Optional args: `--skip-thing` to reuse an existing Thing, `--policy <policy-name>` for a custom IoT policy.

Publish a test event (IAM creds):
```bash
cd infra/aws-cli
./publish-test.sh
```
Optional env vars: `TOPIC` (defaults to `v2x/v1/detections/fleetA/edge-device-001`), `PAYLOAD_FILE` (defaults to `infra/aws-cli/payload.sample.json`).

Provision unauthenticated write API (`POST /detections`):
```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 ./provision-write-api.sh
```
Optional env vars: `INGEST_LAMBDA_NAME` (default `v2x-detections-ingest`), `API_NAME` (default `v2x-detections-api`), `STAGE_NAME` (default `\$default`).

Write API test (uses the provisioned endpoint output):
```bash
curl -X POST -H 'content-type: application/json' \
  -d '{"items":[{"object_id":"traffic_cone_001","timestamp_utc":"2026-02-05T00:00:00Z"},{"object_id":"traffic_cone_002","timestamp_utc":"2026-02-05T00:00:01Z"}]}' \
  'https://<api-id>.execute-api.us-west-1.amazonaws.com/detections'
```
Request body supports:
- single object (`{"object_id":"...","timestamp_utc":"..."}`)
- array of objects (`[{"object_id":"...","timestamp_utc":"..."}]`)
- wrapped batch (`{"items":[...]}`)
- max batch size: 500 items

Provision read-only API (`GET /detections/...`) used by viewer deployments:
```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 ./provision-read-api.sh
```
Optional env vars: `TABLE_NAME` (default `v2x_detections`), `INGEST_LAMBDA_NAME` (default `v2x-detections-ingest`), `READ_LAMBDA_NAME` (default `v2x-detections-read`), `API_NAME` (default `v2x-detections-api`), `STAGE_NAME` (default `\$default`), `ATTACH_DDB_READ_POLICY` (default `true`), `READ_POLICY_NAME` (default `v2x-detections-ddb-read`).

Read API examples (uses the provisioned endpoint output):
- `https://<api-id>.execute-api.us-west-1.amazonaws.com/detections/recent?limit=10`
- `https://<api-id>.execute-api.us-west-1.amazonaws.com/detections/object/traffic_cone_001?limit=10`
- `https://<api-id>.execute-api.us-west-1.amazonaws.com/detections/geohash/f43h7?limit=10`
Pagination:
- All read endpoints return a `next` token when there are more results.
- Use `?next=<token>` (optionally with `limit`) to fetch the next page.

Cleanup:
```bash
cd infra/aws-cli
./cleanup.sh
```
Optional env vars: `TABLE_NAME` (default `v2x_detections`), `LAMBDA_NAME` (default `v2x-detections-ingest`), `RULE_NAME` (default `v2x_detections_to_ddb`), `IOT_POLICY_NAME` (default `v2x-edge-publish`), `THING_NAME` (default `edge-device-001`), `LAMBDA_ROLE_POLICY_NAME` (default `v2x-detections-ddb-put`).

Notes:
- Device certs/keys are written under `infra/aws-cli/.secrets/iot/<thingName>/` (ignored by git).
- `infra/aws-cli/create-device.sh` also writes `device.env` with endpoint/topic values.
- Do not paste AWS access keys into chat or commit them.

### Lightsail viewer (infra/lightsail)
Deploy viewer UI as a container service or instance (region `us-west-2`).
Requires the read-only API Gateway created by `infra/aws-cli/provision-read-api.sh`.

Instance deploy:
```bash
cd infra/lightsail
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export LIGHTSAIL_REGION="us-west-2"
export API_BASE_URL="https://qxacv7wah0.execute-api.us-west-1.amazonaws.com"
./deploy-viewer-instance.sh
```

Force a rebuild/redeploy:
```bash
cd infra/lightsail
AWS_PROFILE="Path-Emerging-Dev-147229569658" LIGHTSAIL_REGION="us-west-2" \
  API_BASE_URL="https://qxacv7wah0.execute-api.us-west-1.amazonaws.com" \
  RECREATE=true ./deploy-viewer-instance.sh
```
Optional env vars: `INSTANCE_NAME` (default `v2x-viewer`), `AVAILABILITY_ZONE` (default `us-west-2a`), `BLUEPRINT_ID` (default `ubuntu_22_04`), `BUNDLE_ID` (default `nano_3_0`).

Optional container service (requires Docker daemon):
```bash
cd infra/lightsail
./deploy-viewer.sh
```
Optional env vars: `SERVICE_NAME` (default `v2x-viewer`), `CONTAINER_NAME` (default `viewer`), `CONTAINER_PORT` (default `3000`), plus `AWS_PROFILE`, `LIGHTSAIL_REGION`, and required `API_BASE_URL`.

Destroy container service:
```bash
cd infra/lightsail
./destroy-viewer.sh
```
Optional env vars: `SERVICE_NAME` (default `v2x-viewer`), plus `AWS_PROFILE`, `LIGHTSAIL_REGION`.

Destroy instance:
```bash
cd infra/lightsail
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export LIGHTSAIL_REGION="us-west-2"
./destroy-viewer-instance.sh
```
Optional env vars: `INSTANCE_NAME` (default `v2x-viewer`), plus `AWS_PROFILE`, `LIGHTSAIL_REGION`.

### Amplify hosting (infra/amplify)
Deploy static viewer + docs (Amplify in `us-west-2`, API in `us-west-1`).
Prereqs: AWS CLI v2 authenticated, `jq`, `curl`, `zip`.

Deploy:
```bash
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export AWS_REGION="us-west-2"
export API_BASE_URL="https://qxacv7wah0.execute-api.us-west-1.amazonaws.com"

cd infra/amplify
./deploy.sh
```
Optional env vars: `APP_NAME` (default `v2x-viewer`), `BRANCH_NAME` (default `main`).

Destroy:
```bash
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export AWS_REGION="us-west-2"

cd infra/amplify
./destroy.sh
```
Optional env vars: `APP_NAME` (default `v2x-viewer`).

Cleanup scope note:
- `infra/aws-cli/cleanup.sh` removes the ingest stack (IoT rule/policy/thing+certs, ingest Lambda, DynamoDB table) but does not delete API Gateway resources or the read Lambda created by `provision-read-api.sh` / `provision-write-api.sh`.

## TODO
- Add any missing local dev workflows beyond the viewer app.
