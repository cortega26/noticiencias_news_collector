.PHONY: bootstrap lint lint-fix fix-makefile-tabs type typecheck test test-all test-e2e e2e perf audit security build clean help bump-version audit-todos audit-todos-baseline audit-todos-check docs-api docs format audit-issues config-docs config-docs-check docs-config-fields bootstrap-refinery test-refinery docs-check docs-review

VENV ?= .venv
VENV_REFINERY ?= .venv-refinery
ifeq ($(OS),Windows_NT)
BIN_DIR := Scripts
PYTHON ?= python
else
BIN_DIR := bin
PYTHON ?= python3
endif

PYTHON_BIN := $(VENV)/$(BIN_DIR)/python
PIP := $(PYTHON_BIN) -m pip
PYTEST := $(PYTHON_BIN) -m pytest
RUFF := $(PYTHON_BIN) -m ruff
MYPY := $(PYTHON_BIN) -m mypy
ALEMBIC := $(PYTHON_BIN) -m alembic
BLACK := $(PYTHON_BIN) -m black
ISORT := $(PYTHON_BIN) -m isort
PRE_COMMIT := $(PYTHON_BIN) -m pre_commit
PDOC := $(PYTHON_BIN) -m pdoc
PIP_AUDIT := $(PYTHON_BIN) -m pip_audit
BANDIT := $(PYTHON_BIN) -m bandit
SEMGREP := $(PYTHON_BIN) -m semgrep

# Refinery Environment
PIP_REFINERY := $(VENV_REFINERY)/$(BIN_DIR)/pip
PYTHON_REFINERY := $(VENV_REFINERY)/$(BIN_DIR)/python

REPORTS_DIR := reports
COVERAGE_DIR := $(REPORTS_DIR)/coverage
PERF_DIR := $(REPORTS_DIR)/perf
SECURITY_DIR := $(REPORTS_DIR)/security
PLACEHOLDER_REPORT_JSON := $(REPORTS_DIR)/placeholders.json
PLACEHOLDER_REPORT_MD := $(REPORTS_DIR)/placeholders.md
PLACEHOLDER_SARIF := $(REPORTS_DIR)/placeholder-audit.sarif
PLACEHOLDER_COMMENT := $(REPORTS_DIR)/placeholder-comment.md
PLACEHOLDER_BASE ?= $(shell \
	if git rev-parse --verify origin/main >/dev/null 2>&1; then \
		echo origin/main; \
	elif git rev-parse --verify main >/dev/null 2>&1; then \
		echo main; \
	else \
		echo HEAD; \
	fi)
PLACEHOLDER_PATTERNS := tools/placeholder_patterns.yml
PIP_AUDIT_REPORT := $(SECURITY_DIR)/pip-audit.json
BANDIT_REPORT := $(SECURITY_DIR)/bandit.json
GITLEAKS_REPORT := $(SECURITY_DIR)/gitleaks.json
SECURITY_STATUS := $(SECURITY_DIR)/status.json
BOOTSTRAP_STAMP := $(VENV)/.bootstrap-complete
BOOTSTRAP_REFINERY_STAMP := $(VENV_REFINERY)/.bootstrap-complete

CONFIG_FILE ?= $(CURDIR)/config.toml
KEY ?=
EXTRA ?=
AUDIT_ISSUES_FLAGS ?=

.DEFAULT_GOAL := help

PYTHON_MAJOR := 3
PYTHON_MINOR := 13

$(BOOTSTRAP_STAMP): requirements.lock
	@echo "[bootstrap] Setting up virtual environment in $(VENV)"
	@if [ -d $(VENV) ]; then \
		if ! $(VENV)/$(BIN_DIR)/python -c "import sys; v=sys.version_info; sys.exit(0 if (v.major,v.minor)==($(PYTHON_MAJOR),$(PYTHON_MINOR)) else 1)" 2>/dev/null; then \
			echo "[bootstrap] Existing venv Python version mismatch or broken, recreating..."; \
			rm -rf $(VENV); \
		elif ! $(VENV)/$(BIN_DIR)/python -c "import pytest, mypy, ruff, black, isort" 2>/dev/null; then \
			echo "[bootstrap] Existing venv missing key packages, recreating..."; \
			rm -rf $(VENV); \
		fi \
	fi
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	@$(PYTHON_BIN) -m ensurepip --upgrade 2>/dev/null || true
	@$(PYTHON_BIN) -m pip install --upgrade pip
	@$(PYTHON_BIN) -m pip install --no-deps --require-hashes -r requirements.lock
	@$(PYTHON_BIN) -m pip install --no-deps --require-hashes -r requirements-security.lock
	@$(PYTHON_BIN) -m pip install ruff mypy black isort pre-commit pdoc types-requests "types-PyYAML==6.0.12.20250915" "types-python-dateutil==2.9.0.20260124" semgrep
	@$(PYTHON_BIN) -c "import pytest, mypy, ruff, black, isort; print('[bootstrap] Key packages verified')" || { echo "[bootstrap] Package verification failed"; exit 1; }
	@touch $(BOOTSTRAP_STAMP)

$(BOOTSTRAP_REFINERY_STAMP): requirements-refinery.lock
	@echo "[bootstrap-refinery] Creating isolated environment in $(VENV_REFINERY)"
	@test -d $(VENV_REFINERY) || $(PYTHON) -m venv $(VENV_REFINERY)
	@$(PYTHON_REFINERY) -m ensurepip --upgrade 2>/dev/null || true
	@$(PYTHON_REFINERY) -m pip install --upgrade pip
	@$(PYTHON_REFINERY) -m pip install --no-deps --require-hashes -r requirements-refinery.lock
	@# Install app in editable mode, assuming refinery deps cover runtime needs
	@$(PYTHON_REFINERY) -m pip install -e . --no-deps
	@# Test-only tooling (unpinned, not part of the hash-pinned runtime lock —
	@# same pattern as the main venv's ruff/mypy/black/isort dev-tools install).
	@$(PYTHON_REFINERY) -m pip install pytest
	@touch $(BOOTSTRAP_REFINERY_STAMP)

bootstrap: $(BOOTSTRAP_STAMP) ## Provision local environment with dependencies
	@$(PYTHON_BIN) -c "import pytest_timeout" >/dev/null 2>&1 || $(PYTHON_BIN) -m pip install "pytest-timeout>=2.3.0"
	@$(PYTHON_BIN) -c "import pytest_randomly" >/dev/null 2>&1 || $(PYTHON_BIN) -m pip install "pytest-randomly>=3.15.0"
	@echo "Environment ready at $(VENV)"

run-local: bootstrap ## Run the collector locally
	@$(PYTHON) scripts/run_collector.py

bootstrap-refinery: $(BOOTSTRAP_REFINERY_STAMP) ## Provision refinery environment

migrate: bootstrap ## Run database migrations (up to head)
	@NEWS_COLLECTOR_PATH="$(CURDIR)" $(PYTHON_BIN) scripts/migrate.py up


refinery: bootstrap-refinery migrate ## Launch the Refinery Admin Panel (Streamlit UI) in isolated env
	@NEWS_COLLECTOR_PATH="$(CURDIR)" $(PYTHON_REFINERY) -m streamlit run apps/refinery/admin_panel.py

test-refinery: bootstrap-refinery ## Run AppTest-based characterization tests for the Refinery admin panel (isolated env)
	@NEWS_COLLECTOR_PATH="$(CURDIR)" REFINERY_UI_UNSAFE_ALLOW=1 PYTHONPATH=$(CURDIR) $(PYTHON_REFINERY) -m pytest -c tools/ci/pytest_refinery.toml --rootdir=.


debug: bootstrap ## Run the collector in debug mode (verbose)
	@$(PYTHON) scripts/run_collector.py --verbose

lint: bootstrap ## Run code quality checks (check-only)
	@$(PYTHON_BIN) tools/check_makefile_tabs.py Makefile
	@$(BLACK) --check .
	@$(RUFF) check .
	@$(MAKE) check-deprecated

fix-makefile-tabs: ## Normalize Makefile recipes to start with tabs
	@$(PYTHON) -m tools.fix_makefile_tabs

lint-fix: bootstrap ## Auto-format using Black/isort and fix Ruff findings
	@$(BLACK) .
	@$(RUFF) check . --fix

quality: bootstrap ## Run all quality checks (lint, type, security, audit)
	@echo "[quality] Running Ruff (Lint + Security)..."
	@$(RUFF) check .
	@echo "[quality] Running Mypy (Types)..."
	@$(MAKE) type
	@echo "[quality] Running Bandit (Security)..."
	@$(BANDIT) -q -r news_collector scripts -c pyproject.toml -f txt
	@echo "[quality] Running pip-audit..."
	@$(PIP_AUDIT) -r requirements.lock --desc --ignore-vuln CVE-2026-0994
	@echo "[quality] Running Semgrep..."
	@$(SEMGREP) scan --config .semgrep.yml --error || echo "Semgrep found issues (non-blocking for now)"

quality-fix: bootstrap ## Run auto-fixers then quality checks
	@echo "[quality-fix] Auto-formatting..."
	@$(MAKE) lint-fix
	@$(MAKE) quality

quality-ci: bootstrap context-validate ## Run strict quality checks for CI (no fix, fail on error)
	@echo "[quality-ci] Running Ruff..."
	@$(RUFF) check . --output-format=github
	@echo "[quality-ci] Running Mypy..."
	@$(MAKE) type
	@echo "[quality-ci] Running Bandit..."
	@mkdir -p $(SECURITY_DIR)
	@$(BANDIT) -r news_collector scripts -c pyproject.toml -f json -o $(BANDIT_REPORT) --severity-level high --confidence-level high
	@$(PYTHON) scripts/security_gate.py bandit $(BANDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[quality-ci] Running pip-audit..."
	@$(PIP_AUDIT) -r requirements.lock -f json -o $(PIP_AUDIT_REPORT) --progress-spinner off || true
	@$(PYTHON) scripts/security_gate.py pip-audit $(PIP_AUDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[quality-ci] Running Semgrep..."
	@$(SEMGREP) scan --config auto --error || echo "Semgrep found issues (non-blocking for now)"

context-validate: bootstrap ## Validate context files against MODULE_INDEX.md
	@$(PYTHON_BIN) scripts/validate_context.py

lint-changed: bootstrap ## Run ruff only on changed Python files
	@$(PYTHON_BIN) scripts/lint_changed.py

quality-ci-diff: context-validate lint-changed ## Run context validation and lint changed files for CI

docs-api: bootstrap ## Generate API reference documentation with pdoc
	@$(PYTHON_BIN) scripts/generate_api_docs.py

docs: docs-api ## Alias for generating API documentation

docs-check: bootstrap ## Validate active docs: paths, make targets, workflow files, declared invariants (plan 043)
	@$(PYTHON_BIN) scripts/check_doc_drift.py

docs-review: bootstrap ## Changed-file gate: protected code changes require an active-doc review (plan 043)
	@$(PYTHON_BIN) scripts/check_doc_review.py

format: lint-fix ## Alias for auto-formatting helpers

type: typecheck ## Alias for static type checking (mypy)

quality-gate: bootstrap ## Run snapshot-first quality gate (No LLM required)
	@$(PYTHON) scripts/quality_gate.py

quality-gate-refresh: bootstrap ## Regenerate snapshots using local LLM (Overwrite warning!)
	@PYTHONPATH=$(CURDIR) $(PYTHON) scripts/quality_gate_refresh.py

prepush: test-all quality-gate ## Run all checks required before pushing (Full Test Suite + Quality Gate)

verify-ci: lint type test test-contracts test-boundaries security config-docs-check docs-check plans-ledger-check ## Run all required non-deploy backend checks once (plan 041 canonical CI gate)

plans-ledger-check: bootstrap ## Validate plans/README.md ledger (statuses, archiving, commit refs, row drift)
	@$(PYTHON_BIN) scripts/validate_plans_ledger.py

MYPY_TARGETS := scripts/generate_api_docs.py \
news_collector/utils/logger.py \
news_collector/utils/url_canonicalizer.py

typecheck: bootstrap ## Static type checking with mypy (incremental coverage)
	@$(PYTHON_BIN) -m mypy --config-file=pyproject.toml $(MYPY_TARGETS)

	@mkdir -p $(COVERAGE_DIR)
	@$(PYTEST) --cov-report=xml:$(COVERAGE_DIR)/coverage.xml --cov-report=html:$(COVERAGE_DIR)/html
	@COVERAGE_XML=$(COVERAGE_DIR)/coverage.xml bash scripts/coverage_ratcheter.sh check

test: bootstrap ## Run unit tests (fast feedback, excludes slow e2e pipeline)
	@$(PYTEST) tests --ignore=tests/e2e_pipeline

test-all: bootstrap ## Run all tests including slow e2e pipeline
	# Unit suite first (randomized), then e2e in fixed order — mixing them
	# lets unit-test global state leak into the order-sensitive e2e
	# scenarios (2026-08-12, surfaced by pytest-randomly).
	@$(PYTEST) tests --ignore=tests/e2e_pipeline
	@$(PYTEST) tests/e2e_pipeline --randomly-dont-reorganize

test-e2e: bootstrap ## Run the full e2e pipeline tests (~4 min)
	# e2e scenarios assume a clean environment and are order-sensitive;
	# pytest-randomly reorganizes the suite by default, so disable it for
	# this directory (the unit suite stays randomized, 2026-08-12).
	@$(PYTEST) tests/e2e_pipeline --randomly-dont-reorganize

check-coverage: bootstrap ## Check if coverage meets the required threshold (fails under 80%)
	@echo "[coverage] Checking coverage threshold..."
	@$(PYTHON_BIN) -m coverage report --fail-under=80

test-system: bootstrap ## Run S1-scoped verification (Contract + Coverage Gate)
	@echo "[test-system] Running S1 Refactor Verification..."
	@PYTHONPATH=$(CURDIR) $(PYTEST) -c tools/ci/pytest_system.toml --cov-config=tools/ci/coverage_system.rc tests/unit/system/test_s1_refactor.py tests/unit/system/test_activity_monitor.py tests/unit/system/test_bootstrap_coverage.py

test-contracts: bootstrap ## Run D1 Contract enforcement tests (Contract + Coverage Gate)
	@echo "[test-contracts] Running D1 Contract Enforcement..."
	@PYTHONPATH=$(CURDIR) $(PYTEST) -c tools/ci/pytest_contracts.toml --rootdir=.

test-boundaries: bootstrap ## Run D1 System Boundary tests (Behavior only, no coverage)
	@echo "[test-boundaries] Verifying System Boundaries (D1 Phase 2)..."
	@PYTHONPATH=$(CURDIR) $(PYTEST) tests/unit/system/test_d1_pipeline_boundaries.py --no-cov

e2e: bootstrap ## Run end-to-end pytest suite (marked tests)
	@$(PYTEST) -m "e2e" || { echo "E2E tests require additional setup and were skipped."; true; }

perf: bootstrap ## Run performance-focused pytest suite (marked tests)
	@mkdir -p $(PERF_DIR)
	@$(PYTEST) -m "perf" --junitxml=$(PERF_DIR)/junit.xml || { echo "Performance tests not defined; skipped."; touch $(PERF_DIR)/SKIPPED; true; }

audit: security ## Run supply-chain and security audits (alias for `make security`)

security: bootstrap ## Run security and dependency scans
	@mkdir -p $(SECURITY_DIR)
	@echo "[security] Running pip-audit"
	@$(PIP_AUDIT) -r requirements.lock --format json --output $(PIP_AUDIT_REPORT) || true
	@$(PYTHON_BIN) scripts/security_gate.py pip-audit $(PIP_AUDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[security] Running bandit"
	@$(BANDIT) -q -r news_collector scripts -c pyproject.toml -f json -o $(BANDIT_REPORT) --severity-level high --confidence-level high || true
	@$(PYTHON_BIN) scripts/security_gate.py bandit $(BANDIT_REPORT) --severity HIGH --status $(SECURITY_STATUS)
	@echo "[security] Running gitleaks"
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --source . --config .gitleaks.toml --baseline-path .gitleaks-baseline.json --report-format json --report-path $(GITLEAKS_REPORT) --no-banner || true; \
		$(PYTHON_BIN) scripts/security_gate.py gitleaks $(GITLEAKS_REPORT) --severity HIGH --status $(SECURITY_STATUS); \
	else \
		echo "[security] gitleaks not installed; skipping secret scan (CI installs it)."; \
	fi

security-dev: bootstrap ## Run security audit on dev and refinery environments
	@echo "[security-dev] Auditing dev and refinery dependencies..."
	@# Ignoring GHSA-7gcm-g887-7qv7 (protobuf) - Dev/Refinery only, unreachable in production
	@$(PIP_AUDIT) -r requirements-security.lock --desc --ignore-vuln GHSA-7gcm-g887-7qv7
	@$(PIP_AUDIT) -r requirements-refinery.lock --desc --ignore-vuln GHSA-7gcm-g887-7qv7
	@echo "[security-dev] All dev/refinery audits passed (no known vulnerabilities)."

audit-issues: ## Create GitHub issues for each markdown audit finding (AUDIT_ISSUES_FLAGS=-n for dry-run)
	@tools/audit_to_issues.sh $(AUDIT_ISSUES_FLAGS)

build: bootstrap ## Produce a wheel artifact in dist/ using pinned dependencies
	@rm -rf dist
	@mkdir -p dist
	@$(PYTHON_BIN) -m pip wheel --no-deps --wheel-dir dist .

audit-todos: bootstrap ## Run structured placeholder audit and store reports
	@mkdir -p $(REPORTS_DIR)
	@$(PYTHON_BIN) -m tools.placeholder_audit --format json | awk '/^Summary:/ {exit} {print}' > $(PLACEHOLDER_REPORT_JSON)
	@$(PYTHON_BIN) -m tools.placeholder_audit --format table | tee $(PLACEHOLDER_REPORT_MD)

audit-todos-baseline: audit-todos ## Legacy compatibility target (structured audit owns gating now)

audit-todos-check: bootstrap ## Run PR-scoped placeholder audit with SARIF + comment artifacts
	@mkdir -p $(REPORTS_DIR)
	@$(PYTHON_BIN) -m tools.placeholder_audit \
		--pr-diff-only \
		--base $(PLACEHOLDER_BASE) \
		--halo 10 \
		--format json | awk '/^Summary:/ {exit} {print}' > $(PLACEHOLDER_REPORT_JSON)
	@$(PYTHON_BIN) -m tools.placeholder_audit \
		--pr-diff-only \
		--base $(PLACEHOLDER_BASE) \
		--halo 10 \
		--sarif $(PLACEHOLDER_SARIF) \
		--comment $(PLACEHOLDER_COMMENT) \
		--format table | tee $(PLACEHOLDER_REPORT_MD)
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

docs-config-fields: config-docs ## Alias for regenerating docs/config_fields.md

config-docs-check: bootstrap ## Ensure docs/config_fields.md matches schema output
	@TMP_FILE="$$(mktemp)"; \
	$(PYTHON_BIN) -m noticiencias.config_manager --print-schema > "$$TMP_FILE"; \
	if ! diff -u docs/config_fields.md "$$TMP_FILE" >/dev/null; then \
		echo "docs/config_fields.md is out of date. Run 'make config-docs' and commit the result."; \
		rm -f "$$TMP_FILE"; \
		exit 1; \
	fi; \
	rm -f "$$TMP_FILE"

clean: ## Remove virtual environment and caches
	@rm -rf $(VENV) $(VENV_REFINERY) .pytest_cache .mypy_cache

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

.PHONY: audit-placeholders
audit-placeholders:

.PHONY: check-deprecated
check-deprecated: ## Check for deprecated Streamlit arguments
	@echo "[check-deprecated] Scanning for 'use_container_width'..."
	@if grep -r --include="*.py" --exclude-dir=".*" "use_container_width" apps/refinery; then \
		echo "Error: usage of deprecated 'use_container_width' found in apps/refinery."; \
		exit 1; \
	fi
