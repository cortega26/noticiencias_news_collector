# Continuous Integration

Status: Active  
Scope: workflow and local-parity reference for the current repo

## Primary PR And Push Workflow

The main workflow is `.github/workflows/ci.yml`.

Current jobs:

- `lint`
- `type`
- `config`
- `test`
- `coverage`
- `e2e`
- `perf`
- `healthcheck`
- `bandit`
- `gitleaks`
- `pip-audit`
- `audit-todos`
- `build-artifacts`

These jobs are the current automation reality. Documentation should not claim a different required-check set than the workflow actually defines.

## Local Parity Commands

Closest local equivalents:

```bash
make bootstrap
make lint
make type
make config-validate
make config-docs-check
make test
make e2e
make perf
make security
make audit-todos-check
make build
```

Additional strict CI path:

```bash
make quality-ci
make quality-gate
```

## Other Active Workflows

### Documentation

- `.github/workflows/docs.yml`
  - link-checks `README.md` and `docs/**`

### Quality And Security

- `.github/workflows/quality.yml`
  - runs `make quality-ci` and `make quality-gate`
- `.github/workflows/placeholder-audit-pr.yml`
- `.github/workflows/placeholder-audit-nightly.yml`

### Architecture And Contract Focus

- `.github/workflows/system-verification.yml`
  - runs `make test-system`
- `.github/workflows/source_reliability.yml`
  - source config, feed reliability, and LLM resilience checks
- `.github/workflows/e2e.yml`
  - legacy E2E contract validation workflow that still exists alongside the main CI workflow

### Operational Automation

- `.github/workflows/audit-inventory-weekly.yml`
  - detects inventory drift against `audit/00_inventory.json`
- `.github/workflows/dependency-lock-check.yml`
- `.github/workflows/manual-lock-sync.yml`
- `.github/workflows/daily_collector.yml`
- `.github/workflows/release.yml`

## Guidance

- When updating docs about automation, update the workflow YAML first if behavior changed, then update this file.
- When proposing branch-protection requirements, reference the current workflow job names exactly.
- Do not describe jobs as required unless branch protection has actually been configured that way outside the repo.
