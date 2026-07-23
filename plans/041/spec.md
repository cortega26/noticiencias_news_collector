# Plan 041 — Add one whole-workspace verification contract

> Working folder for the executor. Source of truth: [`plans/041-add-whole-workspace-verification.md`](../041-add-whole-workspace-verification.md).
> Target: both repos. Branch: `advisor/041-workspace-verification` in both.

## Goal

One command verifies each repository; one command verifies their shared product boundary:

1. **Backend `make verify-ci`** — one local command runs all required non-deploy backend checks once (lint, type, test, contracts, boundaries, security, config-docs).
2. **Frontend `npm run verify:ci`** — one local command runs all required non-deploy frontend checks once (lint, validate:content, build, test:dist, test:audit, test:e2e, check:contract-sync).
3. **Workspace gate `scripts/verify_workspace.sh`** — runs both repo gates + a read-only cross-repo publication scenario (schema parity, artifact fixture, callback contract). Never publishes, pushes, or uses secrets.
4. **Canonical CI ownership** — each required branch-protection check maps to one canonical command; duplicates documented.
5. **Docs** — `docs/ci.md` and frontend contributor docs identify exact local equivalents and failure ownership.

## STOP conditions (binding — from plan)

- STOP if a required branch-protection status cannot be renamed without operator coordination; preserve the name and stage the consolidation.
- STOP if cross-repo checkout requires write/admin credentials; use public/read-only checkout or verified snapshots.
- STOP if a supposed duplicate has materially different scope; document and retain it until equivalence is proven.

## Implementation details

### Step 1 — Inventory checks by behavior and owner

Matrix of every workflow job/Make/npm target. Stored as `plans/041/tests/baselines/check-matrix.md`.

| Check | Backend owner | Frontend owner | Notes |
|---|---|---|---|
| Lint | `make lint` (Ruff+Black+isort) | `npm run lint` (ESLint+Prettier+checks) | |
| Type | `make type` (mypy strict) | `astro check` (via validate:content) | |
| Unit | `make test` | `npm run test:audit` (vitest) | |
| Coverage | `make check-coverage` | `npm run test:coverage` | |
| Contracts | `make test-contracts` | `npm run check:contract-sync` | Cross-repo |
| Boundaries | `make test-boundaries` | — | Backend-only |
| Security | `make security` | `npm audit --omit=dev` | |
| Build | `make build` | `npm run build` | |
| Dist sanity | — | `npm run test:dist` | Frontend-only |
| Browser | — | `npm run test:e2e` | Frontend-only |
| Config docs | `make config-docs-check` | — | Backend-only |
| System | `make test-system` | — | Backend-only |

### Step 2 — Create idempotent repo-level CI entrypoints

**Backend `make verify-ci`**: thin composition of existing targets:
```make
verify-ci: lint type test test-contracts test-boundaries security config-docs-check
```
Fail-closed, no deployments/network smoke, deterministic.

**Frontend `npm run verify:ci`**: thin composition:
```json
"verify:ci": "npm run lint && npm run validate:content && npm run build && npm run test:dist && npm run test:audit && CI=1 npm run test:e2e && npm run check:contract-sync"
```

### Step 3 — Cross-repo publication scenario

`scripts/verify_workspace.sh --backend . --frontend ../noticiencias`:
1. Validate both repo locations are clean git working trees.
2. Run backend `make verify-ci`.
3. Run frontend `npm run verify:ci`.
4. Cross-repo: run `npm run check:contract-sync` pointing at the backend schema.
5. Validate the frontend `/search.json` artifact (if built) has a store entry for every backend publication fixture.
6. Assert `git status --short` is unchanged in both repos.
7. Never publish, push, or use secrets.

### Step 4 — Compose workflows around canonical commands

Update `.github/workflows/ci.yml` (backend) and `.github/workflows/content-guard.yml` (frontend) to call the canonical commands. Consolidate duplicate setup only after artifact/status parity. Keep scheduled/diagnostic jobs separate.

### Step 5 — Stabilize status names and docs

Update `docs/ci.md` and frontend contributor docs with local equivalents and fork/Dependabot behavior.

## Verification (how each piece is proved)

| # | Test file | Asserts | Run |
|---|---|---|---|
| V1 | `tests/harness.sh backend-verify-ci` | `make verify-ci` exits 0 | `bash plans/041/tests/harness.sh backend-verify-ci` |
| V2 | `tests/harness.sh frontend-verify-ci` | `npm run verify:ci` exits 0 (tolerates pre-existing validate:content) | `bash plans/041/tests/harness.sh frontend-verify-ci` |
| V3 | `tests/harness.sh workspace` | `scripts/verify_workspace.sh` exits 0; both `git status --short` unchanged | `bash plans/041/tests/harness.sh workspace` |
| V4 | `tests/harness.sh schema-mismatch` | workspace gate fails on deliberately incompatible schema | `bash plans/041/tests/harness.sh schema-mismatch` |
| V5 | `tests/harness.sh dirty-tree` | workspace gate fails if either repo has uncommitted changes | `bash plans/041/tests/harness.sh dirty-tree` |
| V6 | `tests/harness.sh all` | V1-V3 all green | `bash plans/041/tests/harness.sh all` |

## Out of scope (from plan)

- Merging Git repositories.
- Triggering deployments from pull requests.
- Requiring cross-repo write tokens.
- Changing production behavior.
- Deleting specialized scheduled/manual diagnostics.
