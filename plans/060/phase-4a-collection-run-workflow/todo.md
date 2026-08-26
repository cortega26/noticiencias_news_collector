# Plan 060 / Phase 4a todo: Durable, single-flight collection runs

Execution index for [`spec.md`](spec.md). **spec.md is binding; do not
implement from this checklist alone.** Its STOP conditions are real —
re-verify the current dispatch code path and startup-hook pattern at
implementation time before assuming the spec's design still fits, since
this spec's recon was done before any code changed.

## Step 0 — baseline

- [ ] `make test` and `make type` pass on `main` before any change.
- [ ] Re-read `news_collector/serving/api.py`'s current collection-run
      code (lines cited in spec.md's recon may have drifted) and confirm
      the module-global state, thread dispatch, and status-lookup bug are
      still exactly as spec.md describes before touching anything.

## Step 1 — migration (spec.md Design §1)

- [ ] New Alembic revision: `idempotency_key`, `heartbeat_at`,
      `updated_at`, `error_code`, `error_detail` added to `workflow_runs`;
      status CHECK widened per spec.md (resolve the `completed` vs.
      `succeeded` STOP condition first — check for other readers of
      `workflow_runs.status` before choosing rename-with-backfill vs.
      add-as-synonym).
- [ ] `uq_workflow_runs_one_active_collection`'s partial-index condition
      extended to `status IN ('queued', 'running')`.
- [ ] Upgrade/downgrade round-trip tested against a scratch copy of the
      real dev DB, matching Phase 3c's own migration-safety bar.

## Step 2 — `CollectionRunWorkflow` (spec.md Design §2)

- [ ] New file `news_collector/logic/workflows/collection_run_workflow.py`,
      following the constructor-DI/typed-result convention spec.md's
      recon documents (see `RefineryEngine`/`PROrchestrator` for the
      pattern).
- [ ] `start`, `heartbeat`, `complete`, `fail`, `recover_expired_leases`,
      `get_status` implemented exactly as spec.md Design §2 describes —
      no exceptions used for expected control flow (already-running,
      not-found, lease-recovery-needed are all typed returns).

## Step 3 — HTTP layer (spec.md Design §3)

- [ ] `admin_collect` and `admin_collect_status` call the workflow;
      409/404 mapping added.
- [ ] `recover_expired_leases()` wired into whatever startup-hook pattern
      already exists in `serving/` (find it first — do not invent a new
      app-lifecycle mechanism per spec.md's STOP condition).
- [ ] `_admin_runs`, `_admin_run_lock`, `_admin_run_counter`,
      `_latest_run_id`, `_prune_collect_runs` deleted entirely.

## Step 4 — retention (spec.md Design §4)

- [ ] Terminal-only 90-day cleanup implemented, following whatever
      existing periodic-maintenance pattern this repo already has (check
      `scripts/` first).
- [ ] Test: an old terminal row is pruned; an old-but-`running` row is
      never pruned regardless of age.

## Step 5 — tests (spec.md "Test impact")

- [ ] `test_admin_collect_starts_and_status_lifecycle` updated for the
      new `run_id` shape (deliberately, not left broken).
- [ ] `test_admin_collect_latest_run_past_nine_and_registry_bounded`
      replaced with retention tests; the numeric-recency-ordering intent
      it encoded is re-proven against the new mechanism.
- [ ] New: concurrent-start race → one 202, one 409 (with the existing
      run's id in the body).
- [ ] New: unrecognized `run_id` → 404.
- [ ] New: simulated restart with a stale `running` row → recovered to
      `interrupted` at next startup.
- [ ] `make test` and `make type` green.

## Step 6 — close out

- [ ] `plans/060/todo.md` Phase 4 line updated (collection-run half done;
      note phase-4b's status separately).
- [ ] `plans/README.md` ledger updated.
- [ ] This file fully checked off.
