# Continuous Integration

Status: Active  
Scope: workflow and local-parity reference for the current repo

## One-command gates (plan 041)

| Scope | Command | Contents |
|---|---|---|
| Backend (this repo) | `make verify-ci` | `lint type test test-contracts test-boundaries security config-docs-check plans-ledger-check` |
| Frontend (../noticiencias) | `npm run verify:ci` | `lint validate:content build test:dist test:audit test:e2e check:contract-sync` |
| Whole workspace (read-only) | `bash scripts/verify_workspace.sh --backend . --frontend ../noticiencias` | both gates + schema parity + artifact checks; never publishes, pushes, or uses secrets |

These are the canonical local equivalents of the CI checks. Anything the
workflow runs, these run; anything these run that the workflow does not
(scheduled/diagnostic jobs) is intentionally excluded from the PR gate.

## Primary PR And Push Workflow

The main workflow is `.github/workflows/ci.yml`.

Current jobs:

- `lint` — `make lint`
- `type` — `make type` (mypy strict + full test suite + coverage ratchet)
- `config` — `make config-validate` + `make config-docs-check`
- `contract-parity` — cross-repo frontend schema parity (strict gate)
- `test` — full pytest suite with coverage XML
- `coverage` — coverage ratchet vs base branch
- `perf` — `make perf`
- `healthcheck` — collector health probe
- `build-artifacts` — `make build` + Docker image + smoke
- `update-ci-badge` — CI badge sync (diagnostic)

These jobs are the current automation reality. Documentation should not claim a different required-check set than the workflow actually defines.

## Quality And Security Workflow

`.github/workflows/quality.yml` (job `quality-gate`):

- `make quality-ci` — Ruff (GitHub format), mypy, bandit, pip-audit, semgrep
- `make quality-gate` — snapshot-first quality gate (no LLM)
- gitleaks secret scan (binary downloaded in CI, `make security` runs it locally when installed)

## Local Parity Commands

Closest local equivalents:

```bash
make bootstrap
make lint
make type
make config-validate
make config-docs-check
make test
make test-contracts
make test-boundaries
make security
make quality-gate
make build
make perf
make plans-ledger-check  # plans/README.md ledger drift (statuses, DONE-in-root, commit refs)
```

The complete PR-equivalent local gate is:

```bash
make verify-ci
```

## Other Active Workflows

### Documentation

- `.github/workflows/docs.yml`
  - link-checks `README.md` and `docs/**`

### Architecture And Contract Focus

- `.github/workflows/system-verification.yml`
  - runs `make test-system`
- `.github/workflows/source_reliability.yml`
  - source config, feed reliability, and LLM resilience checks
- `.github/workflows/e2e.yml`
  - legacy E2E contract validation workflow

### Scheduled / Diagnostic (not part of the PR gate)

- `.github/workflows/audit-inventory-weekly.yml` — inventory drift
- `.github/workflows/dependency-lock-check.yml` — lockfile freshness
- `.github/workflows/manual-lock-sync.yml` — manual lockfile refresh
- `.github/workflows/daily_collector.yml` — scheduled collection
- `.github/workflows/mutation.yml` — mutation testing (nightly)
- `.github/workflows/live-source-drift.yml` — live feed cohort sweep
- `.github/workflows/placeholder-audit-pr.yml` / `placeholder-audit-nightly.yml`
- `.github/workflows/release.yml` — release build/publish
- `.github/workflows/fix-makefile-tabs.yml` — self-heal workflow
- `.github/workflows/sync-master.yml` — master mirror sync

## Fork And Dependabot Behavior

- Cross-repo checkouts (frontend schema in `ci.yml`, backend schema in
  `content-guard.yml`) use least-privilege read tokens; on fork/Dependabot
  PRs where secrets are unavailable, the workflows fall back to committed
  snapshots instead of failing.
- `test_contracts_sync.py` runs its strict cross-repo comparison only when
  `CI_EXPECTED_FRONTEND_SCHEMA` is set; locally it skips with a clear
  message. `npm run check:contract-sync` is the local equivalent.
- Scheduled jobs run on the default branch only; PRs never trigger
  deployments or scheduled diagnostics.

## Guidance

- When updating docs about automation, update the workflow YAML first if behavior changed, then update this file.
- When proposing branch-protection requirements, reference the current workflow job names exactly.
- Do not describe jobs as required unless branch protection has actually been configured that way outside the repo.
- `make verify-ci` is the single command that proves this repo's PR gate locally; use it before pushing.
