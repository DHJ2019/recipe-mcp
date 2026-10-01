.DEFAULT_GOAL := help
UV ?= uv
RUN := $(UV) run

.PHONY: help setup doctor demo test lint typecheck eval smoke import-whatsapp categorize refresh-dietary categorization-report serve serve-telegram install-daemon backup nyt-login clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies, create .env (never overwrites), initialise the database
	$(UV) sync
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; else echo ".env already exists; leaving it untouched"; fi
	@chmod 600 .env
	@mkdir -p data .private/tmp-media
	@chmod 700 data .private
	$(RUN) recipe-mcp init-db
	@echo "Setup complete. Next: make doctor && make demo"

doctor: ## Check configuration, database, MCP startup and fixtures without printing secrets
	$(RUN) recipe-mcp doctor

demo: ## Load synthetic recipes and run one sample recommendation
	$(RUN) recipe-mcp demo

test: ## Run the offline test suite (no credentials required)
	$(RUN) pytest -q

lint: ## Ruff lint and format check
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Auto-format with ruff
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## Static type check with mypy
	$(RUN) mypy

eval: ## Run the fixture-based evaluation set offline
	$(RUN) recipe-mcp eval

smoke: ## Opt-in live smoke tests (fail clearly when config is missing)
	$(RUN) recipe-mcp smoke

import-whatsapp: ## Import recipe links from the private WhatsApp export
	$(RUN) recipe-mcp import-whatsapp

categorize: ## Re-apply staples.yaml and categorize recipes that have no classifications yet
	$(RUN) recipe-mcp categorize

refresh-dietary: ## Re-parse stored ingredients and re-run dietary rules (ARGS=--dry-run to preview)
	$(RUN) recipe-mcp refresh-dietary $(ARGS)

categorization-report: ## Write a Markdown review report of proposed classifications
	$(RUN) recipe-mcp categorization-report

serve: ## Start the MCP server over stdio (what MCP clients invoke)
	$(RUN) --env-file .env recipe-mcp serve

serve-telegram: ## Start the Telegram long-polling host (Stage 3)
	$(RUN) --env-file .env recipe-mcp serve-telegram

install-daemon: ## Render the launchd plists (bot and nightly backup) and print the install steps
	$(RUN) recipe-mcp install-daemon

backup: ## Back up the database to BACKUP_DIR, keeping the newest BACKUP_KEEP copies
	$(RUN) recipe-mcp backup

nyt-login: ## One-time interactive NYT sign-in in the dedicated browser profile
	$(UV) sync --extra browser
	$(RUN) --extra browser playwright install chromium
	$(RUN) --extra browser recipe-mcp nyt-login

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build test-results
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
