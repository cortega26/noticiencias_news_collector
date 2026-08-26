# Plan 060 / Phase 4a todo: Durable, single-flight collection runs

Execution index for [`spec.md`](spec.md). **spec.md is binding; do not
implement from this checklist alone.** Its STOP conditions are real —
re-verify the current dispatch code path and startup-hook pattern at
implementation time before assuming the spec's design still fits, since
this spec's recon was done before any code changed.

## Step 0 — baseline

- [x] `make test` and `make type` pass on `main` before any change. (Both
      confirmed green at the outset; re-run clean again at the end —
      `make test`: 2029 passed, 5 skipped; `make type`: 0 mypy errors,
      2042 passed, coverage ratchet OK.)
- [x] Re-read `news_collector/serving/api.py`'s current collection-run
      code (lines cited in spec.md's recon may have drifted) and confirm
      the module-global state, thread dispatch, and status-lookup bug are
      still exactly as spec.md describes before touching anything.
      (Confirmed at `api.py:1080-1209` pre-change — the STOP-2 dispatch
      subtlety check found `_admin_run_lock` is a plain mutex, nothing
      more; safe to remove.)

## Step 1 — migration (spec.md Design §1)

- [x] New Alembic revision `84cf98a379c1`: `idempotency_key`,
      `heartbeat_at`, `updated_at`, `error_code`, `error_detail` added to
      `workflow_runs`; status CHECK widened to `queued`/`running`/
      `succeeded`/`failed`/`cancelled`/`interrupted` (`completed` renamed
      to `succeeded` — operator-confirmed rename, not add-as-synonym,
      after a repo-wide grep found no other reader of
      `workflow_runs.status` and a scratch copy of the real dev DB showed
      0 existing rows).
- [x] `uq_workflow_runs_one_active_collection`'s partial-index condition
      extended to `status IN ('queued', 'running')`; new
      `uq_workflow_runs_idempotency_key_active` partial index added.
- [x] Upgrade/downgrade round-trip tested against a scratch copy of the
      real dev DB (`data/news_v3.db`, 781 real `Article` rows, preserved
      across the round trip), matching Phase 3c's own migration-safety
      bar.

## Step 2 — `CollectionRunWorkflow` (spec.md Design §2)

- [x] New file `news_collector/logic/workflows/collection_run_workflow.py`,
      following the constructor-DI/typed-result convention spec.md's
      recon documents (see `RefineryEngine`/`PROrchestrator` for the
      pattern).
- [x] `start`, `heartbeat`, `complete`, `fail`, `recover_expired_leases`,
      `get_status` implemented exactly as spec.md Design §2 describes —
      no exceptions used for expected control flow (already-running,
      not-found, lease-recovery-needed are all typed returns). Unit
      tests: `tests/unit/logic/workflows/test_collection_run_workflow.py`
      (12 tests, all passing).

## Step 3 — HTTP layer (spec.md Design §3)

- [x] `admin_collect` and `admin_collect_status` call the workflow;
      409/404 mapping added (202 for a started run).
- [x] `recover_expired_leases()` wired into a new FastAPI `lifespan`
      context manager in `create_app()` — operator decision (STOP
      condition 3): no `@app.on_event`/`lifespan` precedent existed
      anywhere in the repo (checked repo-wide, not just `serving/`), so
      `lifespan` (the current, non-deprecated FastAPI mechanism) was
      adopted deliberately rather than reaching for the already-deprecated
      `@app.on_event` just to avoid being "first."
- [x] `_admin_runs`, `_admin_run_lock`, `_admin_run_counter`,
      `_latest_run_id`, `_prune_collect_runs` deleted entirely — confirmed
      via `hasattr` smoke test, no dual-write.

## Step 4 — retention (spec.md Design §4)

- [x] Terminal-only 90-day cleanup implemented as
      `scripts/ops/prune_workflow_runs.py`, an on-demand ops script
      following `scripts/ops/purge_short_articles.py`'s shape (operator
      decision — this repo has no scheduled-job infrastructure).
- [x] Test: an old terminal row is pruned; an old-but-`running` (and
      old-but-`queued`) row is never pruned regardless of age —
      `tests/unit/storage/test_prune_workflow_runs.py` (9 tests).

## Step 5 — tests (spec.md "Test impact")

- [x] `test_admin_collect_starts_and_status_lifecycle` updated for the
      new `run_id` shape (202 status code, stringified integer id).
- [x] `test_admin_collect_latest_run_past_nine_and_registry_bounded`
      replaced with `test_admin_collect_status_uses_true_recency_not_lexical_order`;
      the numeric-recency-ordering intent it encoded is re-proven against
      the new mechanism (DB `started_at`/`id` ordering, crossing the
      two-digit id boundary the old lexicographic bug tripped on).
- [x] New: concurrent-start race → one 202, one 409 (with the existing
      run's id in the body) —
      `test_admin_collect_concurrent_start_yields_one_202_one_409`.
- [x] New: unrecognized `run_id` → 404 —
      `test_admin_collect_status_unknown_run_id_returns_404_not_latest` and
      `test_admin_collect_status_non_numeric_run_id_returns_404`.
- [x] New: simulated restart with a stale `running` row → recovered to
      `interrupted` at next startup —
      `test_admin_collect_restart_recovers_stale_running_row_to_interrupted`
      (uses `with TestClient(app) as client:` — verified empirically that
      a bare `TestClient(app)`, which the shared `api_client` fixture
      uses, does not trigger FastAPI `lifespan` at all).
- [x] `make test` and `make type` green (also fixed a hardcoded
      `HEAD_REVISION` constant in `tests/unit/storage/test_migration_guard.py`
      that the new migration head broke, and one mypy `Literal` narrowing
      error in `admin_collect_status` via an explicit `cast`).

## Step 6 — close out

- [x] `plans/060/todo.md` Phase 4 line updated (collection-run half done;
      phase-4b's status noted separately, not started).
- [x] `plans/README.md` ledger updated (Phase 4a implemented, not yet
      merged — branch `feat/phase-4a-collection-run-workflow`).
- [x] This file fully checked off.
