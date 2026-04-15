.PHONY: help web-dev web-build web-install bridge-install bridge-dry-run deploy-web

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Web (SvelteKit dashboard) ──

web-install: ## Install web dependencies
	cd apps/web && npm ci

web-dev: ## Start web dev server
	cd apps/web && npm run dev

web-build: ## Build web for production
	cd apps/web && npm run build

# ── Bridge (Python CARLA bridge) ──

bridge-install: ## Install bridge Python dependencies
	cd apps/bridge && pip install -r requirements.txt

bridge-dry-run: ## Run bridge in dry-run mode (no CARLA needed)
	cd apps/bridge && python -m digital_twin_bridge.drive_main --dry-run

# ── Deployment ──

deploy-web: ## Deploy web dashboard to AWS Amplify
	cd infra/amplify && ./deploy.sh

# ── Launch (GPU server) ──

launch-drive: ## Start drive server (requires CARLA running)
	./scripts/launch-drive.sh
