# AGENTS.md

## Repo Layout

- `apps/bridge`: Python CARLA bridge (drive server + observation mode).
- `apps/web`: SvelteKit digital twin dashboard. See `apps/web/AGENTS.md` for
  driving-input internals (wheel/pedal gamepad calibration, keyboard fallback,
  WebSocket control transport).
- `scripts/`: Operational launch scripts for the GPU server.
- `infra/aws-cli`: AWS CLI scripts for IoT Core, Lambda, DynamoDB, API Gateway, S3, KVS.
- `infra/amplify`: Deploy the web dashboard to Amplify Hosting.

## App Commands

### Bridge (`apps/bridge`)

Install dependencies:
```bash
cd apps/bridge
pip install -r requirements.txt
```

Dry-run (no CARLA required):
```bash
cd apps/bridge
python -m digital_twin_bridge.drive_main --dry-run
```

Run the drive server (CARLA must be running):
```bash
./scripts/launch-drive.sh
```

Bridge config (env vars, prefix `DTB_`):
- `DTB_CARLA_HOST` (default `localhost`)
- `DTB_CARLA_PORT` (default `2000`)
- `DTB_V2X_API_URL` (default: production read API)
- `DTB_WS_PORT` (default `8765`)
- `DTB_AWS_PROFILE` (default `Path-Emerging-Dev-147229569658`)
- `DTB_S3_BUCKET` (default: production state bucket)

### Web Dashboard (`apps/web`)

```bash
cd apps/web
npm ci
npm run dev
```

Production build:
```bash
cd apps/web
npm run build
```

### Makefile (root)

```bash
make help             # Show all commands
make web-dev          # Start SvelteKit dev server
make web-build        # Production build
make web-install      # npm ci
make bridge-install   # pip install -r requirements.txt
make bridge-dry-run   # Dry-run (no CARLA)
make deploy-web       # Deploy to Amplify
make launch-drive     # Start drive server
```

## Infra Workflows

### IoT Ingest Pipeline (`infra/aws-cli`)

Prereqs: AWS CLI v2 authenticated, `jq`, `zip`.

Provision pipeline in `us-west-1`:
```bash
cd infra/aws-cli
export AWS_PROFILE="your-profile"
export AWS_REGION="us-west-1"
./provision.sh
```

Optional env vars: `TABLE_NAME` (default `v2x_detections`), `LAMBDA_NAME` (default `v2x-detections-ingest`), `RULE_NAME` (default `v2x_detections_to_ddb`), `IOT_POLICY_NAME` (default `v2x-edge-publish`), `THING_NAME` (default `edge-device-001`), `TTL_DAYS` (default `7`), `SKIP_IAM` (default `false`).

Provision read-only API:
```bash
cd infra/aws-cli
./provision-read-api.sh
```

Provision write API:
```bash
cd infra/aws-cli
./provision-write-api.sh
```

Provision state bucket:
```bash
cd infra/aws-cli
./provision-state-bucket.sh
```

Provision video streams:
```bash
cd infra/aws-cli
AWS_REGION=us-west-2 ./provision-video-streams.sh
```

Cleanup:
```bash
cd infra/aws-cli
./cleanup.sh
```

### Amplify Hosting (`infra/amplify`)

Deploy dashboard (Amplify in `us-west-2`, API in `us-west-1`):
```bash
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export AWS_REGION="us-west-2"
export API_BASE_URL="https://<api-id>.execute-api.us-west-1.amazonaws.com"
cd infra/amplify
./deploy.sh
```

Destroy:
```bash
cd infra/amplify
./destroy.sh
```

## Scripts

### `scripts/launch-drive.sh`

Starts the drive server on the GPU server. Checks AWS credentials, activates the CARLA venv, verifies CARLA is running, then launches the WebSocket drive server.

Configurable via env vars:
- `VENV` — path to carla venv activate script
- `AWS_PROFILE` — AWS profile for S3 access
- `CARLA_PORT` — CARLA simulator port (default `2000`)
- `WS_PORT` — WebSocket server port (default `8765`)
