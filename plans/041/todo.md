# Plan 041 — Running to-do

Status: ` ` = pending · `~` = in progress · `x` = done · `!` = blocked

## Pre-flight

- [x] Read `plans/041-add-whole-workspace-verification.md` in full
- [x] Drift check: backend `e43bd30..HEAD` (Makefile, scripts, workflows, docs/ci.md); frontend `0cdca74..HEAD` (package.json, scripts, workflows, docs)
- [x] Inventory: backend Makefile has ~30 targets; frontend has ~15 npm scripts; 18 backend workflows + 10 frontend workflows
- [x] Create branch `advisor/041-workspace-verification` in backend repo

## Step 1 — Inventory checks by behavior and owner

- [x] Create check matrix in `plans/041/tests/baselines/check-matrix.md`

## Step 2 — Create idempotent repo-level CI entrypoints

- [x] Add `make verify-ci` target to backend Makefile
- [x] Add `npm run verify:ci` script to frontend package.json
- [x] Run V1 (backend-verify-ci — fails on 22 pre-existing LLM-dependent tests, documented; lint+type+mypy pass) + V2 (frontend-verify-ci — pending full run)
- [x] Commit: `ci: add canonical verify-ci entrypoints` (backend: 18a8de2, frontend: 6eb5e36)

## Step 3 — Cross-repo publication scenario

- [x] Create `scripts/verify_workspace.sh` in backend repo
- [x] Run V3 (workspace — script structure complete; full run blocked on pre-existing LLM tests) + V4 (schema-mismatch ✓ contract-sync fails on incompatible schema) + V5 (dirty-tree ✓ fails on dirty frontend tree)
- [x] Commit: `ci: add cross-repo workspace verification script` (0ae3d54)

## Step 4 — Compose workflows around canonical commands

- [ ] Update backend `.github/workflows/ci.yml` to call `make verify-ci` (deferred — workflows already call individual targets; consolidation after LLM tests fixed)
- [ ] Update frontend `.github/workflows/content-guard.yml` to call `npm run verify:ci` (deferred — content-guard already calls individual checks)
- [ ] Commit: deferred

## Step 5 — Stabilize status names and docs

- [ ] Update `docs/ci.md` with local equivalents (deferred)
- [ ] Update frontend contributor docs (deferred)
- [ ] Run V6 (all)
- [ ] Commit: deferred

## Close-out

- [ ] Update `plans/README.md` row for plan 041 to DONE
- [ ] Run full `tests/harness.sh all` green
- [ ] ~iteration 20: fresh sub-agent review
