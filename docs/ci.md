# Continuous Integration

Status: Active  
Scope: workflow and local-parity reference for the current repo

## One-command gates (plan 041)

| Scope | Command | Contents |
|---|---|---|
| Backend (this repo) | `make verify-ci` | `lint type test weak-tests-check test-integration test-e2e test-contracts test-boundaries security config-docs-check inventory-check docs-check plans-ledger-check toolchain-check lock-parity-check` |
| Frontend (../noticiencias) | `npm run verify:ci` | `lint validate:content build test:dist check:search-budget test:audit test:e2e check:contract-sync` |
| Whole workspace (requires clean Git worktrees) | `bash scripts/verify_workspace.sh --backend . --frontend ../noticiencias` | both gates + schema parity + artifact checks; frontend builds may generate artifacts or upload derivatives depending on mode/credentials |

These aggregate local commands cover many checks, not every workflow step.
Backend `verify-ci` omits the build/performance/healthcheck-smoke jobs and the
separate `quality-ci`, `quality-gate` and admin checks. Frontend CI adds Worker,
coverage and dependency-graph checks. Follow the applicable workflow and
change matrix; a clean-tree requirement does not make builds filesystem- or
network-read-only.

## Primary PR And Push Workflow

The main workflow is `.github/workflows/ci.yml`.

Current jobs:

- `lint` — `make lint`, then `make toolchain-check && make lock-parity-check`
- `type` — `make type` (mypy on the three Makefile targets + unit-test coverage run + coverage ratchet); uploads `coverage-reports-unit`
- `config` — `make config-validate` + `make config-docs-check`
- `contract-parity` — cross-repo frontend schema parity (strict gate)
- `test` — `make test` unit suite without coverage; integration, E2E, and performance run in separate jobs
- `weak-tests` — `make weak-tests-check`: seconds-long static AST scan for test functions with no assertion, compared against `audit/weak_tests_baseline.json` (fails when the list grows; shrinking is allowed)
- `integration` — checks out the pinned frontend sender (sparse) and Node 24, then `make test-integration` (integration directory and root tests marked `e2e`, including the real cross-repo publication-callback contract), then `make coverage-full` (unit + integration + `e2e`-marked suites in one instrumented run); uploads `coverage-reports-full`
- `pipeline-e2e` — `make test-e2e` (order-sensitive pipeline scenarios, without coverage instrumentation)
- `coverage` — ratchet both profiles: `coverage-reports-unit` feeds `profiles.unit`, `coverage-reports-full` feeds `profiles.full`
- `perf` — `make perf` without coverage instrumentation (fails on collected-test failure; clean skip with `reports/perf/SKIPPED` only when zero perf tests are collected)
- `admin-contracts` — admin OpenAPI/type drift check + admin tests, build and lint (see "Admin contracts")
- `healthcheck-smoke` — runs the collector healthcheck against the empty CI checkout (the schema is created at runtime). With no rows, `latest_ingest` is a warning and the backlog threshold cannot be exceeded, so this job only proves the healthcheck command can run; it is not a dependency of `build-artifacts` and does not assert the operational thresholds. Use [`runbooks/healthcheck.md`](runbooks/healthcheck.md) against a real database for that.
- `build-artifacts` — `make build` + Docker image + smoke
- `update-ci-badge` — CI badge sync (diagnostic)

The `full` profile is the one that measures the `e2e`-marked suites (admin/public API), which the unit profile never collects; the unit profile remains the fast local gate behind `make type`.

`make e2e` is a local gate (not a CI job) with the same contract as `make perf`:
it fails on any real test failure and only exits cleanly when zero `e2e` tests are
collected, writing `reports/e2e/SKIPPED`.

These jobs are the current automation reality. Documentation should not claim a different required-check set than the workflow actually defines.

### Cross-repo publication-callback contract (pinned frontend)

`tests/integration/test_publication_callback_contract.py` imports the **real**
frontend sender (`../noticiencias/scripts/backend-notify.js`) through a Node
subprocess, so it only exercises the contract when that checkout is present.
For a long time CI did not have it, the module skipped, and the job stayed
green while the frontend had stopped emitting `publication_attempt_refs`
(frontend PR #311).

The `integration` job now materialises the sender deliberately:

- `actions/checkout` checks out `cortega26/noticiencias` at the pinned commit
  `7c6ad1242c6cba55e55bed6610006e78a423dd79`, sparse (`scripts/` +
  `package.json`, cone mode off) into `.ci/frontend`, with `fetch-depth: 1` and
  `persist-credentials: false`. `.ci/` is gitignored.
- `actions/setup-node` installs Node 24 (the sender runs on Node built-ins and
  `scripts/utils/*`; the job runs **no `npm install`** — keep it that way).
- `make test-integration` runs with `FRONTEND_REPO_PATH=.ci/frontend`.

This step is **required on the `integration` job**: without it the four
cross-repo test classes silently skip. The skip is fail-closed: when
`FRONTEND_REPO_PATH` is unset and the sibling checkout is absent the module
skips (ordinary local runs), but when the variable is set and the sender is
missing the module fails instead of skipping, so a broken checkout cannot pass.

**Bumping the pin.** When the frontend sender or the callback contract changes,
update the `ref` to the new merged frontend commit (`main`), then re-run the
focused tests against a sparse checkout of that commit:

```bash
rm -rf /tmp/opencode/fe-sparse && mkdir -p /tmp/opencode/fe-sparse
cd /tmp/opencode/fe-sparse && git init -q
git remote add origin https://github.com/cortega26/noticiencias.git
git config core.sparseCheckout true
git config core.sparseCheckoutCone false
git sparse-checkout set scripts/ package.json
git fetch -q --depth 1 origin <new-commit>
git checkout -q FETCH_HEAD
cd -  # back to the backend repo
FRONTEND_REPO_PATH=/tmp/opencode/fe-sparse .venv/bin/pytest \
  tests/integration/test_publication_callback_contract.py -q --no-cov -p no:randomly
```

Expect `8 passed`. Bump the pin in the same change that adopts the frontend
sender change; do not let the workflow track `main`.

## Quality And Security Workflow

`.github/workflows/quality.yml` (job `quality-gate`):

- `make quality-ci` — Ruff, scoped mypy/test coverage, Bandit and pip-audit report gates; Semgrep runs from `.venv-security` with `--config auto` and is non-blocking
- `make quality-gate` — snapshot-first quality gate (no LLM)
- `make security-dev` — audits `requirements-security.lock` and `requirements-refinery.lock` through the shared `scripts/security_gate.py` policy. The security lock is semgrep-free and the allowlist is empty (plan 156 retired the `GHSA-84m7-p3x7-pcfv` exception); semgrep now lives in its own hash-pinned tool lock installed only into `.venv-security`
- gitleaks secret scan (binary downloaded in CI; locally `make security` runs it when installed and fails with an explicit message when it is missing — set `SKIP_SECRET_SCAN=1` to skip that leg deliberately). The CI pin lives in `GITLEAKS_VERSION` in `.github/workflows/quality.yml`; use the same version locally.
- the uploaded `quality-reports` artifact no longer contains the raw gitleaks report: `scripts/sanitize_gitleaks_report.py` writes a copy with the matched `Secret`/`Match` values replaced by a marker, and only that copy (plus the gate status file in the scanned reports directory) is uploaded. The raw report stays on the runner for the gate step. That matters on a public repository, where anyone with read access can download artifacts.
- Plan 160 fixes the gitleaks 8.30 run: `.gitleaks-baseline.json` is refreshed with the pinned CI binary and the test-fixture path is allowlisted.

## Local Parity Commands

Closest local equivalents:

```bash
make bootstrap
make bootstrap-security  # isolated semgrep tool env (.venv-security)
make lint
make type
make config-validate
make config-docs-check
make inventory-check
make test
make weak-tests-check  # assertion-free-test ratchet (static, seconds)
make test-contracts
make test-boundaries
make security
make quality-gate
make build
make perf
make plans-ledger-check  # plans/README.md ledger drift (statuses, DONE-in-root, commit refs)
make toolchain-check  # venv gate tools match the .pre-commit-config.yaml pins
make lock-parity-check  # venv matches requirements.lock (no exceptions)
```

The aggregate backend gate is:

```bash
make verify-ci
```

`make toolchain-check` reads `.pre-commit-config.yaml` (the single source of
truth for gate-tool versions) and fails when ruff, black, isort, bandit, pdoc or
mypy drift from it. `make lock-parity-check` compares the venv with
`requirements.lock` and fails on any mismatch; the runtime/security lock
collisions (click, pyee, smmap, types-requests) were retired by constraining the
security lock with `-c requirements.lock` and emptying the exception map (plan
156), so the map now exists only as a fail-loud mechanism. Both are part of
`make verify-ci`, and both run in the `lint` job of `.github/workflows/ci.yml` —
not only on a developer's machine.

GitPython requires >=3.2.1 to address
[GHSA-83vg-56qc-22m7](https://github.com/advisories/GHSA-83vg-56qc-22m7).
The runtime, refinery and security locks share that patched version. Refresh
with `python scripts/sync_lockfiles.py --upgrade-package gitpython==3.2.1`;
keep unrelated pins and the shared security-gate policy unchanged.

### Venv cache key contract

Every workflow that calls `.github/actions/setup-python-env` passes

```yaml
cache-key: ${{ hashFiles('requirements.lock', 'requirements-security.lock', 'Makefile', '.pre-commit-config.yaml') }}
```

The action keys the `.venv` cache on that fragment and skips `make bootstrap`
when the cache restores, so the key must cover every source of a tool pin: the
lockfiles, the literal gate-tool pins in the `Makefile`, and
`.pre-commit-config.yaml` (the source `toolchain-check` compares against). A pin
change must invalidate the cache, otherwise a restored `.venv` presents tool
versions the pins reject. Trade-off: any `Makefile` edit rebuilds the venv cache
(~1 minute) — that is the intended, safe direction. When adding a workflow that
uses the action, copy that literal unchanged; if the pins ever move to a
dedicated file, update every `cache-key` in the same change.

The semgrep tool environment is cached separately in `.github/workflows/quality.yml`
(path `.venv-security`, key `venv-security-<os>-hashFiles('requirements-semgrep.lock')`).
Its lock is standalone (no `-c requirements.lock`), so that one file fully
defines the environment; a restored cache preserves the bootstrap stamp and
`make bootstrap-security` becomes a no-op.

## Other Active Workflows

### Collector incidents

- `.github/workflows/collector-incident-watcher.yml` — reacts to completed
  `Daily News Collection` runs on the default branch: one stable issue on the
  first failure after a healthy run, at most one update per 24 h per identical
  fingerprint, recovery comment and close on the next success, and the 30 h
  rule for cancellations. Its fail-closed branches and operator steps are in
  [`runbook.md#collector-failure-incidents`](runbook.md#collector-failure-incidents).

### Documentation

- `.github/workflows/docs.yml`
  - link-checks `README.md` and `docs/**`; it does not run `make docs-check`
- `make docs-check` validates selected active docs locally and in `make verify-ci`; it is not a job in the main CI workflow.

### Generated API reference

`docs/api/` is not committed (plan 147). `make docs-api` generates the pdoc
reference into `docs/api/` on demand; do not commit the output. The retired
committed copy was last regenerated on 2026-09-25 and nothing linked or checked
it, so it could silently describe a stale surface.

### Admin contracts

- `.github/workflows/ci.yml` (job `admin-contracts`, on every push/PR): installs
  Python + Node 24 and `npm ci --legacy-peer-deps` in `apps/admin`, then gates
  dependencies with `npm audit --audit-level=high` before running
  `make admin-contracts-check` (fresh OpenAPI export compared against
  `apps/admin/openapi.json`, then `openapi-typescript --check` on the committed
  types), `make admin-test`, `make admin-build` and `make admin-lint`
  (`prettier --check` + `eslint`, the same check as the `admin-lint` pre-commit
  hook).
- The admin Vitest DOM environment uses Happy DOM >=21.0.4, the patched minimum
  for [GHSA-834v-8h66-3h79](https://github.com/advisories/GHSA-834v-8h66-3h79).
  The audit includes development dependencies; the high threshold remains enforced.
- Local regeneration: `make admin-contracts-generate`.
- Ownership: Pydantic models in `news_collector/contracts/admin.py` are the
  source; the exporter is the only writer of `apps/admin/openapi.json`; the
  generated `api.d.ts` is never edited by hand (plan 080 Phase 2).

### Architecture And Contract Focus

- `.github/workflows/system-verification.yml`
  - runs `make test-system`
- `.github/workflows/source_reliability.yml`
  - source config, feed reliability, and LLM resilience checks
- `.github/workflows/e2e.yml` (E2E Contract Test)
  - `pull_request` runs only when the diff touches the collector/export
    surface: `news_collector/collectors/**`, `news_collector/contracts/**`,
    `news_collector/system/**`, `scripts/run_collector.py`,
    `scripts/validate_export.py`, `news_collector/config/sources.yaml`, or the
    workflow itself. Pushes to `main`/`master` and manual dispatch remain
    unfiltered.
  - The dry run is limited to three fast tier-A RSS sources
    (`ieee_spectrum_ai`, `ars_technica_technology_lab`, `nasa_news`) instead of
    all configured sources, then `scripts/validate_export.py` validates the
    export against the frontend contract and fails on a zero-article or invalid
    export.
  - It is not a branch-protection required check today. Do not make it one
    while it is `paths:`-filtered: a PR outside those paths would leave the
    required status pending.
- `.github/workflows/publication-smoke.yml`
  - path-triggered on PRs touching `news_collector/contracts/frontend_schema.py`,
    `news_collector/contracts/publication_validation.py`,
    `news_collector/logic/workflows/frontend_publication_validation.py`,
    `news_collector/logic/workflows/**`, `news_collector/components/publishing/**`,
    `scripts/generate_fixture_post.py`, or `scripts/validate_frontend_publication.py`;
    sparse-checks out the sibling frontend repo and runs
    `scripts/validate_frontend_publication.py` against it

### Inventory baseline (detector + self-heal)

- `.github/workflows/audit-inventory-weekly.yml` — independent detector: compares
  `audit/00_inventory.json` against a fresh snapshot and opens/comments the
  "Inventory drift detected" issue when drift remains.
- `.github/workflows/inventory-autorefresh.yml` — healer: Mondays 05:00 UTC (one
  hour before the audit) and on manual dispatch, checks out `main`, regenerates
  the baseline and pushes only `audit/00_inventory.json` when it drifted; it also
  closes any open drift issue once the baseline is current. It pushes with the
  default `GITHUB_TOKEN`, whose pushes do not trigger further workflow runs, so
  the auto-commit cannot loop.
- Local parity: `make inventory-check` (fails with the refresh remedy when the
  baseline is stale) and `make inventory-refresh` (regenerate + commit);
  `inventory-check` is part of `make verify-ci`.

### Weak-test ratchet (assertion-free tests)

- `make weak-tests-check` — static AST scan of `tests/`
  (`scripts/test_suite_audit.py --static-only`, no pytest run) compared against
  `audit/weak_tests_baseline.json`. It fails when a new `test_*` function has no
  assertion or `raise`, allows entries to shrink, and fails closed when the
  baseline is missing.
- `make weak-tests-baseline` — deliberate, reviewer-visible refresh of the
  baseline. Run it after fixing entries, never to make a red gate green.
- It runs in the `weak-tests` job of `.github/workflows/ci.yml` and in
  `make verify-ci`. The slow `make test-audit` remains the full
  coverage/quality report; the ratchet never runs pytest.

### Other triggers (consult each YAML; some also run on PRs)

- `.github/workflows/audit-inventory-weekly.yml` + `.github/workflows/inventory-autorefresh.yml` — inventory drift detector and self-heal
- `.github/workflows/dependency-lock-check.yml` — lockfile freshness for all
  four hash-pinned locks (`requirements.lock`, `requirements-refinery.lock`,
  `requirements-security.lock`, and the isolated semgrep tool env,
  `requirements-semgrep.lock`; plan 162)
- `.github/workflows/manual-lock-sync.yml` — manual lockfile refresh (regenerates
  and commits the same four)
- `.github/workflows/daily_collector.yml` — scheduled collection
- `.github/workflows/mutation.yml` — mutation testing (weekly, Mon 06:00 UTC, plus a path-filtered `pull_request` run when a PR touches `editorial/categories.py`, `editorial/health_scope.py`, `logic/workflows/publication_identity.py` or `validation/rules.py`): `mutmut run` over the critical pure modules, then `scripts/mutation_score.py --check` fails below the per-module floors in `[tool.mutation.floors]` (local: `make mutation`; measured ~3.5 min for the 9 floored modules with `--max-children 2`)
- `.github/workflows/test-health-weekly.yml` — test health (weekly, Mon 07:00 UTC; manual input `days`, default 14): the whole suite with the clock moved forward (`TIME_SHIFT_DAYS`, `tests/_plugins/time_shift_plugin.py`) so time-dependent tests and accepted-risk exceptions about to expire (pip-audit allowlist) fail here first; not a PR gate (local: `TIME_SHIFT_DAYS=14 make test-timeshift`)
- `.github/workflows/live-source-drift.yml` — live feed cohort sweep
- `.github/workflows/placeholder-audit-pr.yml` / `placeholder-audit-nightly.yml`
- `.github/workflows/release.yml` — release build/publish
- `.github/workflows/fix-makefile-tabs.yml` — self-heal workflow
- `.github/workflows/sync-master.yml` — master mirror sync

## Runner baseline

All workflows pin `runs-on: ubuntu-24.04` (pinned ahead of GitHub's
`ubuntu-latest` → Ubuntu 26 migration on 2026-10-19). Acceptance: full CI green
on the pin PR. Rollback: revert the pin commit. Unpin deliberately only after a
trial run validates the suite on Ubuntu 26.

## Fork And Dependabot Behavior

- Frontend `content-guard.yml` can use a committed backend schema snapshot
  when cross-repo secrets are unavailable. Backend `ci.yml` instead checks
  out the frontend checker and schema; it does not implement that snapshot
  fallback. Do not assume both directions have identical fork behavior.
- `test_contracts_sync.py` runs its strict cross-repo comparison only when
  `CI_EXPECTED_FRONTEND_SCHEMA` is set; locally it skips with a clear
  message. `npm run check:contract-sync` is the local equivalent.
- Scheduled jobs run on the default branch only; PRs never trigger
  deployments or scheduled diagnostics.

## Guidance

- When updating docs about automation, update the workflow YAML first if behavior changed, then update this file.
- When proposing branch-protection requirements, reference the current workflow job names exactly.
- Do not describe jobs as required unless branch protection has actually been configured that way outside the repo.
- Use `make verify-ci` as the aggregate local baseline, plus applicable gates omitted from it (listed above). Its success is not proof of every remote required check.
- **Wiring a new gate: run it report-only first.** The gitleaks gate was "downloaded but
  never run" for weeks (plan 041) and its first real execution surfaced a full backlog
  (33 findings, 30 of them false positives). When adding a new CI gate: (1) run it in
  report-only mode, (2) triage every finding — allowlist/baseline the true non-issues,
  (3) only then enable it as a failure. An always-red gate trains everyone to ignore
  red and lets the first real issue slip through.
- **Secrets gate policy:** `gitleaks` fails on any finding not in `.gitleaks-baseline.json`.
  The baseline pins known historical debt (see issue #249) — new secrets must never be
  added to it; the correct fix for a baseline entry is rotation + history purge, after
  which the entry is deleted.
