# Plan 041: Add one whole-workspace verification contract

> **Executor instructions**: Define canonical local commands first, then make both repositories' CI compose them. Remove duplicate checks only after equivalence is proven. Update plan 041 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- Makefile scripts .github/actions .github/workflows docs/ci.md`
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- package.json scripts .github/workflows docs`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/020-enforce-cross-repo-schema-parity.md, plans/023-connect-and-harden-report-pipeline.md, plans/024-canonicalize-backend-dependencies.md, plans/026-pin-github-actions.md, plans/029-fix-backend-coverage-ratchet.md, plans/031-enforce-representative-frontend-tests.md
- **Category**: dx
- **Planned at**: backend `e43bd30`, frontend `0cdca74`, 2026-07-21

## Why this matters

The product spans two repositories, but no single local or CI command validates their shared publication path. Meanwhile backend `ci.yml`, `quality.yml`, `system-verification.yml`, and lock workflows repeat setup and subsets with divergent tool installs. Canonical repo-level gates plus a cross-repo contract scenario reduce false confidence and wasted CI work.

## Current state

- Backend `Makefile` exposes overlapping `test`, `test-all`, `prepush`, `quality-ci`, `test-system`, contract, performance, and security targets.
- `.github/workflows/ci.yml` owns broad gates but contains its own schema sparse-checkout path; plan 020 corrects that contract gate.
- `.github/workflows/system-verification.yml` repeats Python setup/floating test installs for tests already reachable by broader suites.
- `.github/workflows/quality.yml` repeats bootstrap/static/security work; `.github/workflows/dependency-lock-check.yml` installs its own lock tool path.
- Frontend `.github/workflows/content-guard.yml` is the primary PR gate, while deploy and sync workflows repeat setup/validation subsets.
- Frontend `package.json` has individual checks but no clearly named CI aggregate or full two-repo verification command.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend canonical gate | `make verify-ci` | one local command runs all required non-deploy backend checks once |
| Frontend canonical gate | `npm --prefix ../noticiencias run verify:ci` | one local command runs all required non-deploy frontend/Worker/browser checks once |
| Workspace gate | `./scripts/verify_workspace.sh --backend . --frontend ../noticiencias` | both repo gates and cross-repo publication fixture pass |
| Workflow validation | `.venv/bin/python scripts/validate_workflows.py` | workflows/actions have valid syntax, pinned actions, and no duplicate canonical check IDs |

## Scope

**In scope**: canonical local verification entrypoints, a read-only cross-repo verification script/scenario, shared setup/composite actions, workflow dependency composition, path filters, artifacts, cancellation/timeouts, CI docs, and removal of proven duplicate required checks.

**Out of scope**: merging Git repositories, triggering deployments from pull requests, requiring cross-repo write tokens, changing production behavior, or deleting specialized scheduled/manual diagnostics.

## Git workflow

- Branch: `advisor/041-workspace-verification` in both repositories.
- Commit example: `ci: compose canonical workspace verification`.
- Land shared contract fixtures/commands before making branch-protection check names change.

## Steps

### Step 1: Inventory checks by behavior and owner

Create a matrix of every workflow job/Make/npm target: trigger, inputs, command, external access, output artifact, required status, and overlap. Mark exactly one canonical owner for lint, type, unit, coverage, security, dependency sync, contract parity, build/dist, Worker, and local browser behavior.

**Verify**: every required branch-protection check maps to one canonical command; duplicates have an explicit retain/remove reason.

### Step 2: Create idempotent repo-level CI entrypoints

Add backend `make verify-ci` and frontend `npm run verify:ci` as thin compositions of existing truthful targets from prerequisite plans. They must fail closed, avoid deployments/network smoke, and accept deterministic test/report paths. Keep fast component commands for development.

**Verify**: each command passes twice from a clean install and returns nonzero when a representative fixture/check is intentionally broken.

### Step 3: Add a real cross-repo publication scenario

Implement `scripts/verify_workspace.sh` in the backend (planning/home repo) with explicit `--backend`/`--frontend` paths. Validate clean locations, schema parity, generate a publication artifact from a fixed backend fixture into a temporary copy/staging directory, run frontend content/build/dist checks against it, validate callback/report contract fixtures, and remove temporary output. It must never publish, push, modify real content, or use secrets.

**Verify**: command passes with current sibling repos, leaves both `git status --short` unchanged, and fails on a deliberately incompatible copied schema/artifact.

### Step 4: Compose workflows around canonical commands

Use hash-pinned shared setup from plans 026/030. Make `ci.yml`/`content-guard.yml` call canonical commands or reusable workflows; consolidate duplicate system/quality/lock jobs only after artifact/status parity. Keep scheduled live-source, mutation, deployment, and post-deploy jobs separate. Give cross-repo checkouts least-privilege read access and deterministic refs/snapshots per plan 020.

**Verify**: workflow validator passes; the matrix shows no duplicate execution of the same canonical check on one PR event.

### Step 5: Stabilize status names and docs

Define durable job names for branch protection, migration order, failure artifacts, and ownership. Update `docs/ci.md` and frontend contributor docs with local equivalents and fork/Dependabot behavior.

**Verify**: docs drift/link checks pass and each documented status exists in workflow YAML exactly once.

## Test plan

- Clean/idempotent backend and frontend aggregate commands.
- Workspace success, schema mismatch, invalid generated content, failed frontend build, callback fixture mismatch, dirty-worktree preservation.
- Workflow static tests for pins, duplicate IDs/commands, permissions, timeouts, and required status names.
- Fork/Dependabot paths use committed verified snapshots without secrets.

## Done criteria

- [ ] One command verifies each repository; one command verifies their shared product boundary.
- [ ] Cross-repo verification is read-only to real source/content and uses no publish credentials.
- [ ] Required CI checks each have one canonical owner/execution.
- [ ] Setup, action pins, artifacts, and status names are consistent.
- [ ] Docs identify exact local equivalents and failure ownership.

## STOP conditions

- Stop if a required branch-protection status cannot be renamed without operator coordination; preserve the name and stage the consolidation.
- Stop if cross-repo checkout requires write/admin credentials; use public/read-only checkout or verified snapshots.
- Stop if a supposed duplicate has materially different scope; document and retain it until equivalence is proven.

## Maintenance notes

Add new checks to the repo-level canonical command first, then CI. The workspace gate should validate contracts/artifacts, not duplicate every unit test again.

