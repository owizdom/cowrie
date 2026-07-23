# Cowrie - development commands
#
# The short version:
#   make setup     install everything
#   make dev       run the API (and the app, once the surfaces layer is in)
#   make test      run every test suite
#
# Nothing here talks to a production system. The database is local, the chain is
# local, and every payment partner is simulated.

.DEFAULT_GOAL := help
SHELL := /bin/bash

ORCHESTRATION := orchestration
SURFACES      := surfaces
CONTRACTS     := cusdc

.PHONY: help
help: ## Show this help
	@echo "Cowrie - a cross-border payment network for Africa"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

.PHONY: setup
setup: setup-api setup-contracts ## Install all dependencies
	@echo ""
	@echo "Setup complete. Start with:  make dev"

.PHONY: setup-api
setup-api: ## Install the Python orchestration tier
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv is not installed. Install it with:"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; }
	cd $(ORCHESTRATION) && uv venv --python 3.12 && uv pip install -e ".[dev]"

.PHONY: setup-contracts
setup-contracts: ## Install Foundry dependencies
	@command -v forge >/dev/null 2>&1 || { \
		echo "Foundry is not installed (optional - only needed for contracts)."; \
		echo "  curl -L https://foundry.paradigm.xyz | bash && foundryup"; \
		exit 0; }
	cd $(CONTRACTS) && forge install OpenZeppelin/openzeppelin-contracts@v5.1.0 --no-git 2>/dev/null || true
	cd $(CONTRACTS) && forge install foundry-rs/forge-std --no-git 2>/dev/null || true

# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

.PHONY: dev
dev: ## Run the API on :8000
	cd $(ORCHESTRATION) && .venv/bin/uvicorn cowrie.main:app --reload --port 8000

.PHONY: seed
seed: ## Reset the database and reseed the demo data
	rm -f cowrie-demo.db cowrie-demo.db-wal cowrie-demo.db-shm
	cd $(ORCHESTRATION) && .venv/bin/python -m cowrie.seed

.PHONY: infra
infra: ## Start PostgreSQL 15 and Redis 7 (the SRS datastores)
	docker compose up -d
	@echo "Postgres on :5432, Redis on :6379"
	@echo "Point the API at them with:  export COWRIE_DATABASE_URL=postgresql+psycopg://cowrie:cowrie@localhost:5432/cowrie"

.PHONY: infra-down
infra-down: ## Stop PostgreSQL and Redis
	docker compose down

# ---------------------------------------------------------------------------
# local chain
# ---------------------------------------------------------------------------

.PHONY: anvil
anvil: ## Start a local chain with 2 second blocks (matching Base)
	anvil --block-time 2

.PHONY: chain
chain: ## Deploy the contracts to the local chain
	cd $(CONTRACTS) && ./deploy-local.sh

.PHONY: dev-chain
dev-chain: ## Run the API against the local chain instead of the simulator
	cd $(ORCHESTRATION) && COWRIE_CHAIN_MODE=anvil .venv/bin/uvicorn cowrie.main:app --reload --port 8000

# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------

.PHONY: test
test: test-api test-contracts ## Run every test suite

.PHONY: test-api
test-api: ## Run the Python requirement tests
	cd $(ORCHESTRATION) && .venv/bin/python -m pytest tests/ -v

.PHONY: test-contracts
test-contracts: ## Run the Foundry contract tests
	cd $(CONTRACTS) && forge test -vv

.PHONY: lint
lint: ## Lint and format-check the Python tier
	cd $(ORCHESTRATION) && .venv/bin/ruff check cowrie tests
	cd $(CONTRACTS) && forge fmt --check || true

.PHONY: fmt
fmt: ## Auto-format everything
	cd $(ORCHESTRATION) && .venv/bin/ruff check --fix cowrie tests
	cd $(CONTRACTS) && forge fmt

# ---------------------------------------------------------------------------
# housekeeping
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove build artefacts and the demo database
	rm -f cowrie-demo.db cowrie-demo.db-wal cowrie-demo.db-shm
	rm -rf $(CONTRACTS)/out $(CONTRACTS)/cache $(CONTRACTS)/broadcast
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# android
# ---------------------------------------------------------------------------

.PHONY: apk
apk: ## Build the CowriePay Android package (needs a deployed HTTPS host)
	@command -v bubblewrap >/dev/null 2>&1 || { echo "Install it: npm i -g @bubblewrap/cli"; exit 1; }
	@grep -q REPLACE_WITH_DEPLOYED_HOST android/twa-manifest.json && { \
		echo "Set the deployed host in android/twa-manifest.json first."; \
		echo "See android/README.md — a TWA needs an HTTPS origin to verify against."; \
		exit 1; } || true
	cd android && bubblewrap build
