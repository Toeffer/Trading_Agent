# Trading Agent — operator commands
# Run `make help` to see all targets.

.PHONY: help setup preflight build up down restart logs ps shell test backup sae-hash sae-hash-verify clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ─── First-time setup ─────────────────────────────────────────────────────────
setup:  ## Copy templates → real config files (does NOT fill in secrets)
	@test -f .env || cp .env.example .env && echo "Created .env — edit it"
	@test -f config/exchanges.yaml || cp config/exchanges.yaml.example config/exchanges.yaml
	@test -f config/openclaw.json || cp config/openclaw.json.example config/openclaw.json
	@mkdir -p backups data logs
	@echo "Setup complete. Now edit .env with real credentials, then run: make preflight"

preflight:  ## Verify credentials, API reachability, SAE config — REQUIRED before make up
	docker compose run --rm agent python scripts/preflight.py

# ─── Lifecycle ────────────────────────────────────────────────────────────────
build:  ## Build the agent image
	docker compose build

up:  ## Start the agent in detached mode
	docker compose up -d
	@echo "Agent started. Check Telegram for startup notification."
	@echo "Logs: make logs"

down:  ## Stop the agent (containers removed, volumes preserved)
	docker compose down

restart:  ## Restart the agent
	docker compose restart agent

logs:  ## Tail agent logs
	docker compose logs -f agent

ps:  ## Show container status
	docker compose ps

shell:  ## Open a shell in the running agent container
	docker compose exec agent /bin/bash

# ─── Tests / verification ─────────────────────────────────────────────────────
test:  ## Run unit tests (position sizing, SAE config parse)
	docker compose run --rm agent pytest tests/ -v

# ─── Backups & integrity ──────────────────────────────────────────────────────
backup:  ## Encrypted weekly backup of /data per CLAUDE.md §11 rule 9
	./scripts/backup.sh

sae-hash:  ## Record the current SAE config hash (run after intentional edits)
	./scripts/sae-hash.sh record

sae-hash-verify:  ## Verify SAE config matches recorded hash (run at session start)
	./scripts/sae-hash.sh verify

# ─── Maintenance ──────────────────────────────────────────────────────────────
clean:  ## Remove containers and image (volumes preserved)
	docker compose down --rmi local

clean-data:  ## DESTRUCTIVE — remove all data volumes and logs
	@read -p "This will delete all logs and learned state. Type DELETE to confirm: " confirm && \
		[ "$$confirm" = "DELETE" ] && docker compose down -v && rm -rf data logs || echo "Aborted"
