# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- _Pending release notes_

## [1.3.2] - 2026-02-04

### 🚀 Key Changes

#### 1. Security & Hygiene

- **Consolidated Workflows**: Consolidated security scanning into `ci.yml` by removing redundant `security.yml` and `audit-security.yml` workflows.
- **False Positive Reduction**: Applied strict `# nosec` suppression to known-safe internal scripts (e.g. `scripts/ops/purge_short_articles.py`), eliminating noise from Bandit scans.

#### 2. Developer Experience

- **Cleaner Local Scans**: Added `temp/` to Bandit excludes in `pyproject.toml`.
- **CI Reliability**: Fixed Bandit integration in CI (`set -e` vs exit codes) to ensure the Security Gate runs reliably.
