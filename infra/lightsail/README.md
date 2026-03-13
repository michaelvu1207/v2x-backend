# Lightsail viewer (deprecated)

Lightsail is no longer part of the primary `v2x-backend` deployment path.

The canonical production flow is:

- backend resources in `infra/aws-cli`
- state bucket in `infra/aws-cli/provision-state-bucket.sh`
- dashboard hosting in `infra/amplify`

These Lightsail scripts are retained only for legacy viewer debugging.

## Why `us-west-2`

Lightsail does not support `us-west-1` (North California). Use `us-west-2` (Oregon) for the container service.

## Deploy

```bash
cd infra/lightsail

export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export LIGHTSAIL_REGION="us-west-2"
export API_BASE_URL="https://qxacv7wah0.execute-api.us-west-1.amazonaws.com"

./deploy-viewer-instance.sh
```

To force a rebuild/redeploy (deletes and recreates the instance):

```bash
cd infra/lightsail
AWS_PROFILE="Path-Emerging-Dev-147229569658" LIGHTSAIL_REGION="us-west-2" \
  API_BASE_URL="https://qxacv7wah0.execute-api.us-west-1.amazonaws.com" \
  RECREATE=true ./deploy-viewer-instance.sh
```

## Containers (optional)

If you want a Lightsail *container service* instead of an instance, use `./deploy-viewer.sh` and `./destroy-viewer.sh`.
It requires a running Docker daemon (Docker Desktop on macOS).

## Destroy

```bash
cd infra/lightsail
export AWS_PROFILE="Path-Emerging-Dev-147229569658"
export LIGHTSAIL_REGION="us-west-2"
./destroy-viewer-instance.sh
```
