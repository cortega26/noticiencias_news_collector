# TODO — Plan 109 (batch publication)

Derived from `spec.md`. Mark when verified, not before.

## Step 0 — Baseline (DONE 2026-09-16)

- [x] Drift check on pipeline/serving/admin paths clean; tree clean, on main
- [x] `make lint` exit 0; `make type`: 2602 passed + 4 e2e failures proven PRE-EXISTING (frontend_dist_failure on og:description vs manifest for staged fixture; fails identically with frontend at pre-007 commit 7f8e318 via NOTICIENCIAS_FRONTEND_ROOT worktree; unrelated to Wave 6, out of scope)

## Step 1 — Contract + pipeline (DONE 2026-09-16)

- [x] `AdminPublishBatchRequest` (1..5, positive, unique → 422) + `AdminPublishBatchItem/Started` in `contracts/admin.py`
- [x] `run_publication_batch()` thin wrapper in `publication_pipeline.py` (sequential, per-item explicit outcomes, cap re-asserted); 21 new unit tests green
- [x] `PublicationRunWorkflow.start_batch` + `_run_batch` sharing the single-flight slot via extracted `_enqueue`; heartbeat helper shared with `_run`; `idempotency_key` preserved; all 17 pre-existing workflow tests green

> Reconciled 2026-09-26: a stale duplicate "Step 1" block (identical to the
> checked block above) was removed, and Steps 2-3 were checked against the
> Close-out evidence recorded below (endpoint + GUI landed; OpenAPI snapshot
> regenerated; GUI vitest green).

## Step 2 — Serving wrapper

- [x] Thin endpoint, 409/404/lease semantics preserved
- [x] Boundary tests; `make test-boundaries` green

## Step 3 — Admin GUI

- [x] Triage multi-select + batch status; vitest green

## Close-out (DONE 2026-09-16)

- [x] No identity value changed for prior publishes (17 pre-existing workflow tests green unmodified); `make quality-gate` green
- [x] Full gates: lint/test/test-contracts/test-boundaries/perf green; GUI vitest 35 + astro check clean; OpenAPI snapshot regenerated
- [x] `validate_plans_ledger.py` → OK; row 109 updated
