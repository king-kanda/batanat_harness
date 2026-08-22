# Batanat Agentic Harness
#
# The datastores run on the host (bare metal), not in Docker — see README.
# `uv` is resolved from PATH, falling back to the project-local tools venv.

SHELL := /bin/bash
UV := $(shell command -v uv 2>/dev/null || echo .tools/uv-venv/bin/uv)
API_DIR := apps/api
WEB_DIR := apps/web

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------

.PHONY: setup
setup: tools install ## One-command setup: uv, python deps, node deps, .env, database
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@grep -q '^TOKEN_ENCRYPTION_KEY=.\+' .env || ( \
		KEY=$$(cd $(API_DIR) && $(abspath $(UV)) run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") && \
		sed -i "s|^TOKEN_ENCRYPTION_KEY=.*|TOKEN_ENCRYPTION_KEY=$$KEY|" .env && \
		echo "generated TOKEN_ENCRYPTION_KEY in .env" )
	$(MAKE) migrate seed
	@echo "Setup complete. Run 'make api' and 'make web' in two terminals."

.PHONY: tools
tools: ## Install uv into a project-local venv (no system changes)
	@test -x .tools/uv-venv/bin/uv || (python3 -m venv .tools/uv-venv && .tools/uv-venv/bin/pip -q install uv)
	@$(UV) --version

.PHONY: install
install: ## Install all dependencies
	cd $(API_DIR) && $(abspath $(UV)) sync --all-groups
	bun install

# --- run ---------------------------------------------------------------------

.PHONY: api
api: ## Run the API (http://localhost:8000)
	cd $(API_DIR) && $(abspath $(UV)) run fastapi dev src/batanat_api/main.py --port 8000

.PHONY: web
web: ## Run the web app (http://localhost:3000)
	cd $(WEB_DIR) && bun run dev

.PHONY: services
services: ## Report whether the host datastores are reachable
	@scripts/check-services.sh

# --- database ----------------------------------------------------------------

.PHONY: migrate
migrate: ## Apply all migrations
	cd $(API_DIR) && $(abspath $(UV)) run alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	cd $(API_DIR) && $(abspath $(UV)) run alembic downgrade -1

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="add x"
	cd $(API_DIR) && $(abspath $(UV)) run alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Create the demo user, tender sources and starting Skill.MD
	cd $(API_DIR) && $(abspath $(UV)) run python -m batanat_api.db.seed

.PHONY: reset-db
reset-db: ## Drop everything and rebuild from migrations, then seed
	cd $(API_DIR) && $(abspath $(UV)) run alembic downgrade base
	cd $(API_DIR) && $(abspath $(UV)) run alembic upgrade head
	$(MAKE) seed

# --- quality -----------------------------------------------------------------

.PHONY: check
check: cpu-only lint test typecheck ## Everything CI runs

.PHONY: test
test: ## Run the API test suite
	cd $(API_DIR) && $(abspath $(UV)) run pytest

.PHONY: lint
lint: ## Lint and format-check Python
	cd $(API_DIR) && $(abspath $(UV)) run ruff check .
	cd $(API_DIR) && $(abspath $(UV)) run ruff format --check .

.PHONY: format
format: ## Autoformat Python
	cd $(API_DIR) && $(abspath $(UV)) run ruff format .
	cd $(API_DIR) && $(abspath $(UV)) run ruff check --fix .

.PHONY: typecheck
typecheck: ## Typecheck the web app
	cd $(WEB_DIR) && bun run typecheck

.PHONY: cpu-only
cpu-only: ## Fail if any GPU/CUDA package resolves
	@scripts/check-cpu-only.sh

# --- contracts ---------------------------------------------------------------

.PHONY: types
types: ## Regenerate shared TS types from the Pydantic contracts
	cd $(API_DIR) && $(abspath $(UV)) run python scripts/export_contracts.py
	cd $(WEB_DIR) && bun run generate-routes

# --- docker (optional; not the default path on this machine) ------------------

.PHONY: compose-up
compose-up: ## Start datastores in Docker instead of using host services
	docker compose up -d

.PHONY: compose-down
compose-down: ## Stop the Compose datastores
	docker compose down
