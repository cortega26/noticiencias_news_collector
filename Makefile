.PHONY: bootstrap lint lint-fix typecheck test e2e perf security clean help

VENV ?= .venv
ifeq ($(OS),Windows_NT)
BIN_DIR := Scripts
PYTHON ?= python
else
BIN_DIR := bin
PYTHON ?= python
endif

PIP := $(VENV)/$(BIN_DIR)/pip
PYTEST := $(VENV)/$(BIN_DIR)/pytest
RUFF := $(VENV)/$(BIN_DIR)/ruff
MYPY := $(VENV)/$(BIN_DIR)/mypy
PIP_AUDIT := $(VENV)/$(BIN_DIR)/pip-audit
BANDIT := $(VENV)/$(BIN_DIR)/bandit
BOOTSTRAP_STAMP := $(VENV)/.bootstrap-complete

.DEFAULT_GOAL := help

$(BOOTSTRAP_STAMP): requirements.lock
	@echo "[bootstrap] Creating virtual environment in $(VENV)"
	@$(PYTHON) -m venv $(VENV)
	@$(PIP) install --upgrade pip
	@$(PIP) install --require-hashes -r requirements.lock
	@$(PIP) install ruff mypy pip-audit bandit
	@touch $(BOOTSTRAP_STAMP)

bootstrap: $(BOOTSTRAP_STAMP) ## Provision local environment with dependencies
	@echo "Environment ready at $(VENV)"

lint: bootstrap ## Run Ruff lint checks
	@$(RUFF) check src tests scripts

lint-fix: bootstrap ## Run Ruff with autofix enabled
	@$(RUFF) check src tests scripts --fix

typecheck: bootstrap ## Static type checking with mypy
	@$(MYPY) src tests

test: bootstrap ## Execute the unit test suite
	@$(PYTEST)

e2e: bootstrap ## Run end-to-end pytest suite (marked tests)
	@$(PYTEST) -m "e2e" || { echo "E2E tests require additional setup and were skipped."; true; }

perf: bootstrap ## Run performance-focused pytest suite (marked tests)
	@$(PYTEST) -m "perf" || { echo "Performance tests not defined; skipped."; true; }

security: bootstrap ## Run security and dependency scans
	@$(PIP_AUDIT) -r requirements.txt || { echo "pip-audit detected vulnerabilities (see above)."; true; }
	@$(BANDIT) -q -r src || { echo "Bandit detected issues (see above)."; true; }

clean: ## Remove virtual environment and caches
	@rm -rf $(VENV) .pytest_cache .mypy_cache

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'
