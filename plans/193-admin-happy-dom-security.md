# Plan 193 — Restore the admin dependency security gate

Status: PARTIAL — local implementation verified; independent final review and integration pending

## Specification

The backend `Admin contracts` job for main `704f0e22` fails before contract
validation because `happy-dom` is affected by GHSA-834v-8h66-3h79. Update only
`apps/admin/package.json` and its npm lock to a patched Happy DOM release;
retain Node 24, existing CI thresholds, application behavior, and all Python
locks. This is a Critical dependency/security change under `docs/AGENTS.md`.

The [reviewed advisory](https://github.com/advisories/GHSA-834v-8h66-3h79)
lists versions 17.0.0–21.0.3 as affected and 21.0.4 as patched. The official npm
registry reports Node >=20 for 21.0.4, compatible with the admin's >=24 <25.
Use the existing caret convention with a patched minimum of `^21.0.4` and
resolve 21.0.4 in the committed lock; avoid broad audit fixes. Leave the
pre-existing moderate fast-uri advisories outside this high-severity repair.

Update the active admin CI documentation with the test-environment dependency
and audit requirement. Register this plan and refresh inventory for its new
Markdown file. Existing admin tests exercise application behavior through
Happy DOM; a test that only asserts the package version adds no useful proof.

## Acceptance and verification

- Reproduce the baseline high advisory via `npm audit --audit-level=high`.
- Install the updated committed tree with `npm ci --legacy-peer-deps` on Node 24;
  rerun the exact audit gate and record zero high/critical advisories.
- Run `make admin-contracts-check`, `make admin-test`, `make admin-build`, and
  `make admin-lint` against this worktree. Require unchanged generated artifacts.
- Run repository baseline `make lint`, `make type`, `make test`, dependency
  security gate `make quality`, `make docs-check`, inventory check/refresh, and
  `python scripts/validate_plans_ledger.py` as required by backend governance.
  Record any pre-existing or environment failures explicitly.
- Inspect package/lock changes and ensure unrelated dependency versions,
  source files, Python dependencies, and CI policy remain unchanged.
- Obtain independent review before the commit/publication role proceeds.
  This implementation task ends with an uncommitted, reviewable candidate.

## Todo

- [x] Read governance, inspect admin/CI boundary, verify live base and isolate worktree.
- [x] Reproduce baseline and verify patched release/Node compatibility in official sources.
- [x] Update dependency/lock and active documentation.
- [x] Pass exact audit, admin tests/check/build/lint and contract drift checks.
- [x] Run repository/security/documentation gates; refresh and verify inventory.
- [x] Record results, inspect diff, and request independent review from parent.

## Results

Baseline: Node v24.19.0; `npm audit --audit-level=high` exits 1 with one high
Happy DOM advisory and one moderate fast-uri dependency finding. Upstream CI
run 40102228536 / job 120896561198 shows the same failure.

Verified candidate results (2026-10-24, Node v24.19.0 / npm 11.17.0):

- `npm ci --legacy-peer-deps`: passes against the final lock.
- `npm audit --audit-level=high`: exit 0; 0 high/critical, 1 pre-existing
  moderate fast-uri dependency finding.
- `make admin-contracts-check admin-test admin-build admin-lint`: exit 0;
  OpenAPI/types unchanged, 96 tests across four files, Astro check has zero
  errors/warnings/hints, ten pages built, Prettier/ESLint pass.
- `make lint docs-check inventory-check plans-ledger-check lock-parity-check`:
  exit 0; 15 active docs checked, zero inventory drift, 69/69 Python runtime
  pins match the isolated environment.
- `make quality SEMGREP='.venv-security/bin/python -m semgrep'`: exit 0;
  Ruff, mypy, Bandit and pip-audit pass (no known Python vulnerabilities).
  Its `make type` run: 4,439 passed / 40 skipped / 190 deselected in 141.93s,
  unit coverage 90.08% versus 88.44% baseline, coverage ratchet passes.
- `make test`: exit 0; 4,439 passed / 40 skipped / 190 deselected in 100.95s.
  Local skips include 35 tests with absent sibling-frontend contract artifacts
  in this isolated worktree and five existing optional/live-test skips. Hosted CI
  provisions the frontend fixtures; these local counts do not claim that proof.
- Semgrep limitation: the module invocation above exits on a deprecation and
  the existing Make target treats Semgrep as non-blocking. A separate real scan
  (`.venv-security/bin/python .venv-security/bin/semgrep scan --config
  .semgrep.yml --error`) completed with zero scan errors and exits 1 on 603
  findings in 130 Python files. All 130 finding files and `.semgrep.yml` match
  HEAD byte for byte; this dependency repair introduces none of those findings.
- Final npm lock diff changes only the root Happy DOM range and Happy DOM's
  version, resolved tarball and integrity. All other package records match HEAD.
  `git diff --check` passes. No application, Python-lock or CI-policy changes.

The copied Python environment initially had three stale packages; installing
existing `requirements.lock` with hashes restored exact runtime parity before
all final backend runs. Initial overlapping bootstrap attempts were stopped
inside this worktree; no canonical dependencies or WIP files were modified.
Independent review, commit, PR CI and integration remain parent-owned steps.
