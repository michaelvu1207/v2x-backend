# Amplify Hosting (`v2x-backend`)

This deploys the SvelteKit digital twin dashboard from `apps/v2x-digital-twin-web`.

The dashboard is hosted in Amplify (`us-west-2`) and reads live state assets from the dedicated
`v2x-backend` S3 state bucket in `us-west-1`.

## Deploy

```bash
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export AWS_REGION="us-west-2"
export API_BASE_URL="https://<api-id>.execute-api.us-west-1.amazonaws.com"
export STATE_BUCKET="v2x-backend-state-147229569658-us-west-1"

cd /Users/maikyon/Documents/Programming/v2x-backend/infra/amplify
./deploy.sh
```

Optional:

- `APP_NAME` defaults to `v2x-backend`
- `BRANCH_NAME` defaults to `main`
- `STATE_BASE_URL` overrides the bucket-derived URL
- `STATE_PATH` defaults to `/api/state.json`
- `MAP_DATA_PATH` defaults to `/api/map-data.json`

## Destroy

```bash
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export AWS_REGION="us-west-2"

cd /Users/maikyon/Documents/Programming/v2x-backend/infra/amplify
./destroy.sh
```
