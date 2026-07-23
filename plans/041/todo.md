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

- [ ] Add `make verify-ci` target to backend Makefile
- [ ] Add `npm run verify:ci` script to frontend package.json
- [ ] Run V1 (backend-verify-ci) + V2 (frontend-verify-ci)
- [ ] Commit: `ci: add canonical verify-ci entrypoints`

## Step 3 — Cross-repo publication scenario

- [ ] Create `scripts/verify_workspace.sh` in backend repo
- [ ] Run V3 (workspace) + V4 (schema-mismatch) + V5 (dirty-tree)
- [ ] Commit: `ci: add cross-repo workspace verification script`

## Step 4 — Compose workflows around canonical commands

- [ ] Update backend `.github/workflows/ci.yml` to call `make verify-ci`
- [ ] Update frontend `.github/workflows/content-guard.yml` to call `npm run verify:ci`
- [ ] Commit: `ci: compose workflows around canonical commands`

## Step 5 — Stabilize status names and docs

- [ ] Update `docs/ci.md` with local equivalents
- [ ] Update frontend contributor docs
- [ ] Run V6 (all)
- [ ] Commit: `docs(ci): stabilize status names and local equivalents`

## Close-out

- [ ] Update `plans/README.md` row for plan 041 to DONE
- [ ] Run full `tests/harness.sh all` green
- [ ] ~iteration 20: fresh sub-agent review
