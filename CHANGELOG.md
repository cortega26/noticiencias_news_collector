# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- _Pending release notes_

## [1.3.3] - 2026-02-08

### Fixed

- **Configuration**: Fixed critical `yaml.parser.ParserError` in `prompts.yaml` by correcting indentation.
- **Reliability**: Resolved `TypeError` in `RSSCollector` by ensuring timezone-aware datetime comparisons in circuit breaker logic.
- **Workflows**: Fixed `daily_collector.yml` failure by removing unsupported `--headless` argument from `run_collector.py`.
- **Infrastructure**: Resolved `scripts/sync_lockfiles.py` regression with `pip>=26.0` by pinning compatibility version.
- **Hygiene**: Standardized `PyYAML` casing in lockfiles to prevent CI/Local flakiness.

### Changed

- **Documentation**: Significantly expanded `RUNBOOK.md` with a new "Referencia de Herramientas y Scripts" section.
- **Quality**: Refactored Alembic migrations and test utilities to pass strict linting (Ruff/Mypy) and applied Code Style formatting.

## [1.3.2] - 2026-02-04

### 🚀 Key Changes

#### 1. Security & Hygiene

- **Consolidated Workflows**: Consolidated security scanning into `ci.yml` by removing redundant `security.yml` and `audit-security.yml` workflows.
- **False Positive Reduction**: Applied strict `# nosec` suppression to known-safe internal scripts (e.g. `scripts/ops/purge_short_articles.py`), eliminating noise from Bandit scans.

#### 2. Developer Experience

- **Cleaner Local Scans**: Added `temp/` to Bandit excludes in `pyproject.toml`.
- **CI Reliability**: Fixed Bandit integration in CI (`set -e` vs exit codes) to ensure the Security Gate runs reliably.
