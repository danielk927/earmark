# Earmark task runner. `make help` lists targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help

HUB  := uv run --quiet --project services/hub
CONC := uv run --quiet --project services/concierge
MEM  := uv run --quiet --project services/memory_agent

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup

.PHONY: setup
setup: ## Install every dependency (uv projects, npm packages)
	cd contracts/python && uv sync --quiet
	cd services/hub && uv sync --quiet
	cd services/concierge && uv sync --quiet
	if [ -f services/memory_agent/pyproject.toml ]; then cd services/memory_agent && uv sync --quiet; fi
	npm install --silent
	cd contracts/ts && npm install --silent
	if [ -f dashboard/package.json ]; then cd dashboard && npm install --silent; fi

.PHONY: convex-init
convex-init: ## First-time local Convex deployment (no account) + secrets from .env
	CONVEX_AGENT_MODE=anonymous npx convex dev --once
	set -a; source .env; set +a; \
	  npx convex env set EARMARK_HUB_SECRET "$$EARMARK_HUB_SECRET"; \
	  npx convex env set EARMARK_READ_SECRET "$$EARMARK_READ_SECRET"

# ---------------------------------------------------------------- run

.PHONY: dev
dev: demo-sim ## Alias for demo-sim

.PHONY: demo-sim
demo-sim: ## Full stack with the keyboard-driven simulator (no hardware). SCENARIO=full_demo replays a scenario instead
	@if [ -n "$(SCENARIO)" ]; then scripts/run_stack.sh sim --scenario scenarios/$(SCENARIO).jsonl; \
	 else scripts/run_stack.sh sim; fi

.PHONY: demo-uwb-sim
demo-uwb-sim: ## Full stack with a simulated UWB wearer (scripted walk to the counter); KEYS=1 moves the wearer from the keyboard
	@if [ -n "$(KEYS)" ]; then scripts/run_stack.sh sim --interactive --adapters simulator,uwb_sim; \
	 else scripts/run_stack.sh sim --adapters simulator,uwb_sim; fi

.PHONY: demo-live
demo-live: ## Full stack with real adapters (NFC spot readers + BLE fobs)
	scripts/run_stack.sh live

.PHONY: convex
convex: ## Convex local backend (foreground)
	npm run dev

.PHONY: hub
hub: ## Hub only (adapters from config/hub.json or EARMARK_ADAPTERS)
	$(HUB) earmark-hub

.PHONY: concierge
concierge: ## Concierge only
	$(CONC) earmark-concierge

.PHONY: memory-agent
memory-agent: ## Fetch.ai memory agent
	$(MEM) earmark-memory run

.PHONY: dashboard
dashboard: ## Dashboard dev server (reads VITE_CONVEX_URL from .env)
	set -a; source .env; set +a; cd dashboard && npm run dev

.PHONY: mac
mac: ## Build and sign mac/build/Earmark.app and EarmarkSpatialSpike.app
	mac/build_app.sh

.PHONY: mac-open
mac-open: ## Launch the Earmark Mac app
	open -n mac/build/Earmark.app

.PHONY: spike
spike: ## Launch the spatial-audio gate spike
	open -n mac/build/EarmarkSpatialSpike.app

# ---------------------------------------------------------------- data and demo control

.PHONY: seed
seed: ## Seed Convex (idempotent)
	npm run seed

.PHONY: reset
reset: ## Back to the demo starting state: bus reset (if the hub runs) + Convex reset (trials are kept)
	-$(HUB) earmark-send reset 2>/dev/null || echo "hub not running; skipped bus reset"
	npm run --silent reset

.PHONY: tail
tail: ## Print bus traffic
	$(HUB) earmark-tail

.PHONY: uwb-record
uwb-record: ## Record a UWB field session to var/fieldlog/NAME.jsonl (type markers + Enter; NAME defaults to a timestamp)
	$(HUB) earmark-fieldkit record var/fieldlog/$(or $(NAME),$(shell date +%Y%m%d-%H%M%S)).jsonl

.PHONY: uwb-gates
uwb-gates: ## Show how to check the UWB gates on a recorded log
	@echo "earmark-fieldkit ranging LOG --anchor uwb_1 --truth 0.5,1,2,3"
	@echo "earmark-fieldkit track LOG --path 'x1,y1;x2,y2' [--from M --to M --hold-from M --hold-to M]"
	@echo "earmark-fieldkit taps LOG --spots 'x1,y1;x2,y2'"
	@echo "earmark-fieldkit latency LOG"
	@echo "run as: $(HUB) earmark-fieldkit <subcommand> ...  (exit 0 = PASS, 1 = FAIL)"

.PHONY: trial
trial: ## Run one Earmark-vs-baseline trial (brief 5.I)
	$(HUB) python scripts/trial.py

.PHONY: latency
latency: ## Latency report from logs/latency.jsonl
	python3 scripts/latency_report.py

.PHONY: calibrate
calibrate: ## Tape-measure calibration of config/space.json
	python3 scripts/calibrate.py

.PHONY: scenarios
scenarios: ## Regenerate scenarios/*.jsonl from scripts/gen_scenarios.py
	python3 scripts/gen_scenarios.py

# ---------------------------------------------------------------- tests

.PHONY: test
test: contracts-test hub-test concierge-test ranging-test convex-test memory-test dashboard-test mac-test e2e-test ## Run every test suite

.PHONY: contracts-test
contracts-test: ## Contracts: every example, config file, and scenario (Python, TS, Swift)
	cd contracts/python && uv run --quiet pytest -q
	cd contracts/ts && npm run --silent check
	cd contracts/swift && swift test 2>&1 | tail -1

.PHONY: hub-test
hub-test:
	cd services/hub && uv run --quiet pytest -q && uvx --quiet ruff check .

.PHONY: concierge-test
concierge-test:
	cd services/concierge && uv run --quiet pytest -q && uvx --quiet ruff check .

.PHONY: ranging-test
ranging-test: ## Phone position service, with virtual phones
	cd services/ranging && uv run --quiet pytest -q && uvx --quiet ruff check .

.PHONY: ranging
ranging: ## Phone position service (phones connect to it; see locator/docs/PHONE_BEACONS.md)
	cd services/ranging && uv run --quiet earmark-ranging serve

.PHONY: convex-test
convex-test:
	npm test --silent && npm run --silent typecheck

.PHONY: memory-test
memory-test:
	@if [ -f services/memory_agent/pyproject.toml ]; then cd services/memory_agent && uv run --quiet pytest -q && uvx --quiet ruff check .; else echo "memory agent not built yet"; fi

.PHONY: dashboard-test
dashboard-test:
	@if [ -f dashboard/package.json ]; then cd dashboard && npm test --silent && npm run --silent typecheck && npm run --silent build; else echo "dashboard not built yet"; fi

.PHONY: mac-test
mac-test:
	@if [ -f mac/Package.swift ]; then cd mac && swift test --scratch-path /tmp/earmark-mac-build 2>&1 | tail -3  # outside Documents: macOS file metadata there breaks code signing; else echo "mac app not built yet"; fi

.PHONY: e2e-test
e2e-test:
	@if [ -d tests/e2e ] && ls tests/e2e/test_*.py >/dev/null 2>&1; then cd tests/e2e && uv run --quiet --project ../../services/hub pytest -q -p no:cacheprovider .; else echo "no e2e tests yet"; fi
