# AWS CLI: `v2x-backend` Provisioning

This folder provisions the `v2x-backend` data plane in **`us-west-1`**:

- MQTT ingest: IoT Core -> `v2x-backend-ingest` -> DynamoDB
- Read API: HTTP API -> `v2x-backend-read`
- Public state bucket for digital twin state + snapshots

## Security note

Do **not** paste AWS access keys into chat or commit them to git.

If you already shared credentials, treat them as compromised:
- If they are temporary STS creds, let them expire and issue new ones.
- If they are long-lived, **deactivate/rotate immediately** in IAM.

## Prereqs

- AWS CLI v2 authenticated (recommended: SSO or a named profile)
- `jq` and `zip` available

## Provision

```bash
cd infra/aws-cli

# Optional: use a specific profile
export AWS_PROFILE="your-profile"

# Region is fixed by default to us-west-1, override if needed:
export AWS_REGION="us-west-1"

./provision.sh
```

Default resource names:

- DynamoDB table: `v2x-backend-detections`
- Ingest Lambda: `v2x-backend-ingest`
- Read Lambda: `v2x-backend-read`
- HTTP API: `v2x-backend-api`
- IoT rule: `v2x_backend_detections_to_ddb`
- IoT policy: `v2x-backend-edge-publish`

### If your role can’t call `iam:*` (common with SSO)

If you see `AccessDenied` for `iam:GetRole` / `iam:CreateRole`, don’t create a new role:

- Create/choose an existing IAM role for Lambda in the AWS console (or via your platform team).
- Ensure it trusts `lambda.amazonaws.com` and has `dynamodb:PutItem` on the table plus basic CloudWatch Logs permissions.
- Run:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 SKIP_IAM=true \
  LAMBDA_ROLE_ARN="arn:aws:iam::<account-id>:role/<existing-role>" \
  ./provision.sh
```

If your principal can’t edit IAM roles but you can `iam:PassRole`, you still need the role to already include DynamoDB permissions.

If you *can* add an inline policy to that existing role (still no new role), you can have the script add `dynamodb:PutItem` for you:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 SKIP_IAM=true \
  LAMBDA_ROLE_ARN="arn:aws:iam::<account-id>:role/<existing-role>" \
  ATTACH_DDB_PUT_POLICY=true \
  ./provision.sh
```

Artifacts:
- Device cert/key written under `./.secrets/iot/<thingName>/` (ignored by git)

## Create another device (Thing + cert)

```bash
cd infra/aws-cli
./create-device.sh edge-device-002
```

Note: `./provision.sh` will not generate new certificates for `THING_NAME` if one is already attached.

## Publish a test event (IAM creds, not device cert)

```bash
cd infra/aws-cli
./publish-test.sh
```

## Read and write API

Provision the write route:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 ./provision-write-api.sh
```

Provision the read routes:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 ./provision-read-api.sh
```

Example write request:

```bash
curl -X POST -H 'content-type: application/json' \
  -d '{"object_id":"traffic_cone_001","timestamp_utc":"2026-02-05T00:00:00Z"}' \
  'https://<api-id>.execute-api.us-west-1.amazonaws.com/detections'
```

Example read request:

```bash
curl 'https://<api-id>.execute-api.us-west-1.amazonaws.com/detections/recent?limit=5'
```

## State bucket

Provision the dedicated public bucket for digital twin state assets:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-1 ./provision-state-bucket.sh
```

This creates a bucket named `v2x-backend-state-<account-id>-us-west-1` by default and seeds:

- `api/state.json`
- `api/map-data.json`
- public read access for `api/*` and `snapshots/*`

## Video streams

Provision the Kinesis Video Streams in `us-west-2`:

```bash
cd infra/aws-cli
AWS_PROFILE="your-profile" AWS_REGION=us-west-2 ./provision-video-streams.sh
```

Defaults:

- Stream prefix: `v2x-backend-cam-`
- Camera IDs: `ch1 ch2 ch3 ch4`
- Retention: `24` hours requested; existing streams are left at their current retention if already higher

The read API also exposes:

- `GET /video/session/{camera_id}`

This endpoint returns a short-lived HLS playback URL for the named camera stream.

## Cleanup

```bash
cd infra/aws-cli
./cleanup.sh
```

## Legacy decommission

After the new stack is verified, remove the old `v2x-detections-*` and `v2x-viewer` resources:

```bash
cd infra/aws-cli
./decommission-legacy-v2x.sh
```
