# v2x-backend

Canonical repo for the V2X ingest API, CARLA bridge, and digital twin dashboard.

## Apps

- `apps/v2x-digital-twin-bridge`: Python bridge that polls the read API, spawns CARLA props, captures snapshots, and publishes `api/state.json` plus snapshots to S3.
- `apps/v2x-digital-twin-web`: SvelteKit dashboard deployed to Amplify. Runtime config comes from `config.json`.
- `apps/v2x-viewer`: legacy Express API viewer kept for debugging.
- `apps/v2x-viewer-static`: legacy static viewer/docs kept for debugging.

## Canonical Workflow

1. Provision the backend data plane and API:

```bash
cd infra/aws-cli
./provision.sh
./provision-read-api.sh
./provision-write-api.sh
./provision-state-bucket.sh
AWS_REGION=us-west-2 ./provision-video-streams.sh
```

2. Deploy the dashboard:

```bash
cd infra/amplify
API_BASE_URL="https://<api-id>.execute-api.us-west-1.amazonaws.com" \
STATE_BUCKET="v2x-backend-state-147229569658-us-west-1" \
./deploy.sh
```

3. Run the bridge:

```bash
cd apps/v2x-digital-twin-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DTB_V2X_API_URL="https://<api-id>.execute-api.us-west-1.amazonaws.com/detections/recent" \
python -m digital_twin_bridge
```

## Runtime Config

`apps/v2x-digital-twin-web/static/config.json` and the Amplify deployment expect:

```json
{
  "apiBaseUrl": "https://<api-id>.execute-api.us-west-1.amazonaws.com",
  "stateBaseUrl": "https://v2x-backend-state-147229569658-us-west-1.s3.us-west-1.amazonaws.com",
  "statePath": "/api/state.json",
  "mapDataPath": "/api/map-data.json",
  "videoCameraIds": ["ch1", "ch2", "ch3", "ch4"]
}
```

## Live Video

- Kinesis Video Streams are provisioned in `us-west-2`
- Camera stream names default to:
  - `v2x-backend-cam-ch1`
  - `v2x-backend-cam-ch2`
  - `v2x-backend-cam-ch3`
  - `v2x-backend-cam-ch4`
- The API exposes `GET /video/session/{camera_id}` and returns a short-lived HLS URL for browser playback
- The dashboard requests HLS sessions through the API; browser clients do not use AWS credentials directly

## Notes

- The MQTT topic pattern remains `v2x/v1/detections/+/+`.
- `dt-snapshots-path` is treated as legacy mixed-use storage and is not the target for new `v2x-backend` assets.
- `infra/aws-cli/decommission-legacy-v2x.sh` is the post-cutover cleanup entrypoint for the old `v2x-detections-*` / `v2x-viewer` stack.
