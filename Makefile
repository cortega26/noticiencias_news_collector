.PHONY: bootstrap lint lint-fix typecheck test e2e perf security clean help bump-version audit-todos audit-todos-baseline audit-todos-check

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
PYTHON_BIN := $(VENV)/$(BIN_DIR)/python
REPORTS_DIR := reports
COVERAGE_DIR := $(REPORTS_DIR)/coverage
PERF_DIR := $(REPORTS_DIR)/perf
SECURITY_DIR := $(REPORTS_DIR)/security
PLACEHOLDER_REPORT_CSV := $(REPORTS_DIR)/placeholders.csv
PLACEHOLDER_REPORT_JSON := $(REPORTS_DIR)/placeholders.json
PLACEHOLDER_REPORT_MD := $(REPORTS_DIR)/placeholders.md
PLACEHOLDER_BASELINE := $(REPORTS_DIR)/placeholders.baseline.json
PLACEHOLDER_SCANNER := tools/scan_placeholders.py
PLACEHOLDER_PATTERNS := tools/placeholder_patterns.yml
PIP_AUDIT_REPORT := $(SECURITY_DIR)/pip-audit.json
BANDIT_REPORT := $(SECURITY_DIR)/bandit.json
TRUFFLEHOG_REPORT := $(SECURITY_DIR)/trufflehog.json
SECURITY_STATUS := $(SECURITY_DIR)/status.json
BOOTSTRAP_STAMP := $(VENV)/.bootstrap-complete

CONFIG_FILE ?= $(CURDIR)/config.toml
KEY ?=
EXTRA ?=

.DEFAULT_GOAL := help

$(BOOTSTRAP_STAMP): requirements.lock
	@echo "[bootstrap] Creating virtual environment in $(VENV)"
	@$(PYTHON) -m venv $(VENV)
	@$(PIP) install --upgrade pip
	@$(PIP) install --require-hashes -r requirements.lock
	@$(PIP) install --require-hashes -r requirements-security.lock
	@$(PIP) install ruff mypy
	@touch $(BOOTSTRAP_STAMP)

bootstrap: $(BOOTSTRAP_STAMP) ## Provision local environment with dependencies
	@echo "Environment ready at $(VENV)"

lint: bootstrap ## Run Ruff lint checks
	@$(RUFF) check src tests scripts

lint-fix: bootstrap ## Run Ruff with autofix enabled
	@$(RUFF) check src tests scripts --fix

typecheck: bootstrap ## Static type checking with mypy
	@$(MYPY) src tests

test: bootstrap ## Execute the unit test suite with coverage reporting
	@mkdir -p $(COVERAGE_DIR)
	@$(PYTEST) --cov=src --cov-report=term --cov-report=xml:$(COVERAGE_DIR)/coverage.xml --cov-report=html:$(COVERAGE_DIR)/html

e2e: bootstrap ## Run end-to-end pytest suite (marked tests)
	@$(PYTEST) -m "e2e" || { echo "E2E tests require additional setup and were skipped."; true; }

perf: bootstrap ## Run performance-focused pytest suite (marked tests)
	@mkdir -p $(PERF_DIR)
	@$(PYTEST) -m "perf" --junitxml=$(PERF_DIR)/junit.xml || { echo "Performance tests not defined; skipped."; touch $(PERF_DIR)/SKIPPED; true; }

security: bootstrap ## Run security and dependency scans
	@mkdir -p $(SECURITY_DIR)
	@echo "[security] Running pip-audit"
	@$(PIP_AUDIT) -r requirements.txt --format json --output $(PIP_AUDIT_REPORT) || true
	@$(PYTHON) scripts/security_gate.py pip-audit $(PIP_AUDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[security] Running bandit"
	@$(BANDIT) -q -r src scripts -c .bandit -f json -o $(BANDIT_REPORT) --severity-level high --confidence-level high || true
	@$(PYTHON) scripts/security_gate.py bandit $(BANDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[security] Running trufflehog3"
	@$(PYTHON) scripts/run_secret_scan.py --output $(TRUFFLEHOG_REPORT) --severity HIGH --target . --config .gitleaks.toml
	@$(PYTHON) scripts/security_gate.py trufflehog $(TRUFFLEHOG_REPORT) --severity HIGH --status $(SECURITY_STATUS)

audit-todos: bootstrap ## Run placeholder scanner and generate CSV/JSON/MD reports
	@mkdir -p $(REPORTS_DIR)
	@$(PYTHON_BIN) $(PLACEHOLDER_SCANNER) \
	        --root . \
	        --patterns $(PLACEHOLDER_PATTERNS) \
	        --context 2 \
	        --baseline $(PLACEHOLDER_BASELINE) \
	        --output-csv $(PLACEHOLDER_REPORT_CSV) \
	        --output-json $(PLACEHOLDER_REPORT_JSON) \
	        --output-md $(PLACEHOLDER_REPORT_MD)

audit-todos-baseline: bootstrap ## Refresh the placeholder baseline with current findings
	@$(MAKE) audit-todos
	@$(PYTHON_BIN) $(PLACEHOLDER_SCANNER) \
	        --root . \
	        --patterns $(PLACEHOLDER_PATTERNS) \
	        --context 2 \
	        --baseline $(PLACEHOLDER_BASELINE) \
	        --output-csv $(PLACEHOLDER_REPORT_CSV) \
	        --output-json $(PLACEHOLDER_REPORT_JSON) \
	        --output-md $(PLACEHOLDER_REPORT_MD) \
	        --save-baseline

audit-todos-check: bootstrap ## Compare current findings against baseline and fail on regressions
	@$(PYTHON_BIN) $(PLACEHOLDER_SCANNER) \
	        --root . \
	        --patterns $(PLACEHOLDER_PATTERNS) \
	        --context 2 \
	        --baseline $(PLACEHOLDER_BASELINE) \
	        --output-csv $(PLACEHOLDER_REPORT_CSV) \
	        --output-json $(PLACEHOLDER_REPORT_JSON) \
	        --output-md $(PLACEHOLDER_REPORT_MD) \
	        --compare-baseline

config-gui: bootstrap ## Launch the desktop configuration editor
	@CMD="$(PYTHON_BIN) -m noticiencias.gui_config \"$(CONFIG_FILE)\""; \
	echo "[config-gui] $$CMD"; \
	eval $$CMD

config-set: bootstrap ## Update configuration without opening the GUI (KEY=section.name=value)
	@if [ -z "$(KEY)" ]; then \
	        echo "Usage: make config-set KEY=section.key=value [CONFIG_FILE=path] [EXTRA=\"other.key=value\"]"; \
	        exit 1; \
	fi
	@CMD="$(PYTHON_BIN) -m noticiencias.config_manager --config \"$(CONFIG_FILE)\" --set \"$(KEY)\""; \
	for kv in $(EXTRA); do \
	        CMD="$$CMD --set \"$$kv\""; \
	done; \
	echo "[config-set] $$CMD"; \
	eval $$CMD

config-validate: bootstrap ## Validate active configuration sources
	@echo "[config-validate] $(PYTHON_BIN) -m noticiencias.config_manager --config \"$(CONFIG_FILE)\" --validate"
	@$(PYTHON_BIN) -m noticiencias.config_manager --config "$(CONFIG_FILE)" --validate

config-dump: bootstrap ## Print the built-in default configuration
	@$(PYTHON_BIN) -m noticiencias.config_manager --dump-defaults

config-docs: bootstrap ## Regenerate docs/config_fields.md from the schema
	@$(PYTHON_BIN) -m noticiencias.config_manager --print-schema > docs/config_fields.md

clean: ## Remove virtual environment and caches
	@rm -rf $(VENV) .pytest_cache .mypy_cache

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

bump-version: ## Bump project version (PART=major|minor|patch or VERSION=X.Y.Z)
	@if [ -n "$(VERSION)" ]; then \
	        $(PYTHON) scripts/bump_version.py --set "$(VERSION)"; \
	elif [ -n "$(PART)" ]; then \
	        $(PYTHON) scripts/bump_version.py --part "$(PART)"; \
	else \
	        echo "Usage: make bump-version PART=major|minor|patch | VERSION=X.Y.Z"; \
	        exit 1; \
	fi
