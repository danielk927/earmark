# Earmark task runner. `make help` lists targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT := $(shell pwd)

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

.PHONY: contracts-test
contracts-test: ## Validate every contract example, config file, and scenario (Python, TS, Swift)
	cd contracts/python && uv run --quiet pytest -q
	cd contracts/ts && npm run --silent check
	cd contracts/swift && swift test 2>&1 | tail -1

.PHONY: scenarios
scenarios: ## Regenerate scenarios/*.jsonl from scripts/gen_scenarios.py
	python3 scripts/gen_scenarios.py

.PHONY: test
test: contracts-test ## Run every test suite
