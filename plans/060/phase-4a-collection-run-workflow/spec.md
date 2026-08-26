# Plan 060 / Phase 4a: Durable, single-flight collection runs

> Part of Plan 060, master spec.md "Phase 4: Make admin collection and
> source mutation real workflows" (lines 429-457) — this sub-phase covers
> the collection-run half of that phase's two concrete defects. The
> source-catalog half is [`phase-4b-source-catalog-workflow`](../phase-4b-source-catalog-workflow/spec.md),
> split out the same way Phase 2 (2a/2b/2c) and Phase 3 (3a/3b/3c) were,
> because this is a schema migration plus a new workflow class plus HTTP
> and test rewrites — too much for one PR to review well.

## Why this phase exists

`news_collector/serving/api.py` runs admin collection entirely in process
memory: a module-level dict (`_admin_runs`), a bare `threading.Thread(daemon=True)`
per request, and a most-recent-run fallback that silently returns the
wrong run's status for an unrecognized `run_id`. A server restart loses
every run record, and nothing stops two concurrent `POST /v1/admin/collect`
calls from both starting (evidence table, master spec.md line 67: "Run
state is lost on restart and single-flight is not enforced").

## Recon findings (this session, code-verified via a dedicated Explore pass — see the investigation transcript for exact citations)

**The current implementation, exactly:**
- Module-global state: `_admin_run_lock`, `_admin_runs: Dict[str, Dict]`,
  `_admin_run_counter`, `_latest_run_id` (`api.py:105-109`) — pure process
  memory, nothing durable.
- `_start_collect_run` (`api.py:1090-1165`) launches
  `threading.Thread(target=_run, daemon=True, name=run_id).start()`
  (`api.py:1164`) with no check for an already-running run — single-flight
  is not enforced at all today.
- `admin_collect_status` (`api.py:1186-1209`): `target = run_id if run_id
  and run_id in _admin_runs else None`, then falls through to
  `_latest_run_id` — an unrecognized `run_id` silently returns the *latest*
  run's status with HTTP 200, not a 404. This is the exact bug work item 2
  fixes.
- `_prune_collect_runs` (`api.py:1080-1088`) keeps only the 2 most recent
  runs by count, with **no status check** — a still-`running` row can be
  evicted mid-flight. `test_admin_collect_latest_run_past_nine_and_registry_bounded`
  (`tests/test_serving_admin_api.py:1001-1057`) encodes this "keep 2"
  behavior today and must be rewritten, not silently left passing against
  new code — see "Test impact" below.

**The `workflow_runs` table (Phase 3a, already merged) does not match
what this phase needs, and does not match master spec.md's own described
data contract (lines 152-171) or ADR-0006's schema:**

| Needed for this phase | Actually present (`models.py:535-648`) |
|---|---|
| Opaque stable `id` | bare autoincrement `Integer` |
| `idempotency_key` | **absent** |
| `status` incl. `queued`/`succeeded`/`interrupted` | CHECK only allows `running`/`completed`/`failed`/`cancelled` — **`queued` cannot even be inserted today** |
| heartbeat timestamp (for lease-expiry recovery) | **absent** |
| `updated_at` | **absent** |
| `error_code`/`error_detail` | **absent** — only one undifferentiated `run_metadata` JSON column |
| `version` (optimistic CAS) | **absent** |

Per the operator's decision below, this phase migrates the table to add
what's missing, but does **not** add a `version` column — this codebase's
one proven CAS pattern, `LifecycleRepository.transition_publication_attempt`
(`lifecycle_repository.py:217-251`), is state-based
(`UPDATE ... SET status=to WHERE id=? AND status=from`, checking
`rowcount == 1`) and its own docstring is explicit that no version-column
precedent exists anywhere in this codebase (`lifecycle_repository.py:18-26`).
Introducing one here for the first time, with no other code ever reading
it, is exactly the kind of premature abstraction this program's own
practice avoids.

**Existing single-flight mechanism, keep as-is:** a partial unique index
already enforces "one running collection at a time":
`Index("uq_workflow_runs_one_active_collection", "run_type", unique=True,
sqlite_where=text("run_type = 'collection' AND status = 'running'"))`
(`models.py`, near line 526-532). This is functionally sound for this
phase's single `run_type='collection'` case and does not need an
`active_key` column redesign — extend the CHECK constraint so `'queued'`
rows are covered by the same index condition (`status IN ('queued',
'running')`), since a queued-but-not-yet-running duplicate request should
also conflict.

**`LifecycleRepository` has zero methods for `workflow_runs`** — its own
docstring says so explicitly (`lifecycle_repository.py:1-11`): only
`publication_attempts` and `editorial_decisions` are populated so far.
Every method `CollectionRunWorkflow` needs (create, heartbeat, transition,
recover-expired-lease, lookup-by-id) is new work, not a gap-fill.

**Established workflow-class convention** (from `RefineryEngine`,
`PROrchestrator`, `ManualUrlIngestService` — see recon transcript for
exact citations): constructor takes explicit dependencies (`db`/`db_manager`,
never a global), module-level logger via
`get_logger().create_module_logger(...)`, public methods return a typed
result (dataclass or dict with a `status` field) rather than raising for
*expected* failure modes (e.g. "already running" is a return value the
route maps to 409, not an exception used for control flow) — matching
`transition_publication_attempt`'s "CAS miss is not an error" philosophy.
`CollectionRunWorkflow` follows this shape.

**Deployment topology** (shared finding with Phase 4b, cited here since it
also bears on whether in-process thread dispatch is safe): every tracked
deployment artifact shows a single process — `Dockerfile.serving` runs
plain `uvicorn` with no `--workers` flag, `docker-compose.serving.yml`
defines exactly one `serving` service with no replica config, and SQLite
is the deliberate, operator-chosen production database (`docs/database_deployment.md`,
plan 046, 2026-08-11) — itself constraining safe multi-writer concurrency.
Per the operator's decision, this phase documents single-writer as the
binding deployment assumption rather than redesigning around a hypothetical
multi-instance topology nothing in this repo's tracked config supports.

## Operator decisions (2026-08-26)

- **Migrate `workflow_runs`, reuse state-based CAS.** A new Alembic
  migration adds `idempotency_key`, `heartbeat_at`, `updated_at`,
  `error_code`, `error_detail`, and widens the status CHECK to
  `('queued','running','succeeded','failed','cancelled','interrupted')`.
  No `version` column. `id` stays autoincrement `Integer` (already opaque
  enough for this use — nothing here needs a UUID/string ID; the master
  plan's "opaque stable ID" concern was about not leaking internal
  sequencing semantics to callers, which a plain integer already satisfies
  as long as the HTTP layer doesn't expose ordering guarantees beyond
  "distinct identifier").
- **Single-writer deployment, documented as a binding assumption** (shared
  with Phase 4b — this phase's own use of `threading.Thread` for dispatch
  is unaffected either way, since the *durability* fix is the DB row, not
  the dispatch mechanism; the single-writer decision matters more for
  Phase 4b's file-locked YAML writes).

## Design

### 1. Migration — extend `workflow_runs`

New Alembic revision, additive only (matches every prior Phase 3
migration's own precedent — no data loss, no column removal):
- `idempotency_key VARCHAR NULL` — caller-supplied or server-generated key
  used for the single-flight check; unique together with `run_type` via a
  partial index scoped the same way as the existing active-collection
  index (only enforced while a row is `queued`/`running` — a completed
  run's key can be reused for the next run).
- `heartbeat_at TIMESTAMPTZ NULL` — updated periodically while a run is
  in flight; a `running` row whose `heartbeat_at` is older than a
  configured lease timeout (see Design §2) is eligible for lease-expiry
  recovery.
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` — bumped on every state
  transition, standard audit column this table currently lacks entirely.
- `error_code VARCHAR NULL`, `error_detail TEXT NULL` — populated on a
  `failed`/`interrupted` transition; `run_metadata` stays as the
  catch-all for the run's request payload and success summary (do not
  also cram error detail into it once dedicated columns exist).
- Widen `ck_workflow_runs_status` to include `'queued'`, `'succeeded'`
  (an actual synonym for the existing `'completed'` — **STOP and confirm
  with the operator before deciding whether to rename `'completed'` to
  `'succeeded'` or add `'succeeded'` as a second value**; renaming a value
  already in production data needs a backfill step this migration must
  either include or explicitly defer, not silently skip), and
  `'interrupted'` (a process-restart-observed run — distinct from
  `'cancelled'`, which is operator-requested).
- Extend `uq_workflow_runs_one_active_collection`'s partial-index
  condition from `status = 'running'` to `status IN ('queued', 'running')`.

### 2. `CollectionRunWorkflow` (`news_collector/logic/workflows/collection_run_workflow.py`, new)

Follows the established convention (Design recon above): constructor
`__init__(self, db_manager, *, lease_timeout_seconds=...)`, module logger,
public methods return typed results.

- `start(self, requested_payload: dict) -> CollectionRunStartResult` —
  inserts a `workflow_runs` row with `status='queued'`, `run_type='collection'`,
  `idempotency_key`. If the partial unique index rejects the insert
  (another run is already queued/running), catch the resulting
  `IntegrityError` and return a typed "already running" result (not raise)
  — the route maps this to HTTP 409 with the existing run's id, per the
  established "CAS miss is not an error" convention. On success, dispatches
  the actual collection work the same way today's code does (a background
  thread is fine — the durability fix is the DB row existing *before*
  dispatch, not a change to how the work itself runs), transitions the row
  to `running` once the runner actually starts, and returns the row's id.
- `heartbeat(self, run_id) -> bool` — updates `heartbeat_at`/`updated_at`
  on a `running` row; called periodically by the running collection
  runner. Returns `False` (not an exception) if the row is no longer
  `running` (e.g. it was already recovered as expired by another path) —
  the caller should treat this as "stop, someone else owns this now."
- `complete(self, run_id, *, summary: dict) -> bool` — CAS transition
  `running → succeeded`, following `transition_publication_attempt`'s
  exact pattern (`UPDATE ... WHERE id=? AND status='running'`, `rowcount
  == 1`).
- `fail(self, run_id, *, error_code: str, error_detail: str) -> bool` —
  same CAS shape, transitions to `failed`.
- `recover_expired_leases(self) -> list[int]` — finds every `running` row
  whose `heartbeat_at` is older than the lease timeout (or `NULL` — a row
  that started but never heartbeat once, e.g. crashed immediately) and
  CAS-transitions each to `interrupted`. Returns the list of recovered
  run ids for logging/alerting. Called once at process startup (this
  phase's answer to "restart recovery is deterministic" from the master
  plan's acceptance criteria) — not on a timer, since the only process
  that could be holding a stale lease is the one that just restarted.
- `get_status(self, run_id: int | None) -> CollectionRunStatusResult` —
  looks up a specific run by id if given; returns a typed "not found"
  result (not the latest run) if `run_id` is given but doesn't exist.
  Only returns the most recent run when `run_id` is `None` (the "give me
  the current state" case the status-polling test already relies on for
  a fresh request with no `run_id` param).

### 3. HTTP layer changes (`serving/api.py`)

- `admin_collect` (`api.py:1167-1184`) calls
  `CollectionRunWorkflow.start(...)`; maps an "already running" result to
  `409` with the existing run's id in the response body (the master plan's
  acceptance criterion: "concurrent collect requests yield one 202 and one
  typed 409").
- `admin_collect_status` (`api.py:1186-1209`) calls
  `CollectionRunWorkflow.get_status(run_id)`; maps "not found" (a named,
  unrecognized id) to `404` — never falls through to the latest run.
- Call `recover_expired_leases()` once during app startup (wherever the
  serving app's other startup hooks live — grep for existing `@app.on_event("startup")`
  or lifespan context first; follow that pattern rather than inventing a
  new startup mechanism).
- Delete `_admin_runs`, `_admin_run_lock`, `_admin_run_counter`,
  `_latest_run_id`, and `_prune_collect_runs` entirely — no dual-write,
  no compatibility shim. This phase's whole point is that the DB row is
  now the only source of truth.
- No new workflow logic added to `serving/` beyond request
  parsing/response mapping/HTTP status mapping — this matches the master
  plan's explicit instruction (work item 5) and this sub-phase's own scope.

### 4. Terminal-only 90-day retention

A new scheduled or on-demand cleanup (match whatever pattern
`scripts/` already uses for periodic maintenance — check for an existing
retention/cleanup script before inventing a new entry point) deletes
`workflow_runs` rows where `status IN ('succeeded','failed','cancelled','interrupted')`
(terminal) and `finished_at < now() - 90 days`. A row in `queued`/`running`
is never eligible regardless of age (this is the direct fix for the
"still-running row evicted mid-flight" bug `_prune_collect_runs` has
today). Add a test asserting an old-but-still-`running` row survives
cleanup and an old terminal row does not.

## Test impact (be explicit about what breaks, don't let it surprise reviewers)

- `test_admin_collect_starts_and_status_lifecycle` (`tests/test_serving_admin_api.py:700-758`)
  asserts the `run_id` string starts with `"collect-"`. Once `run_id` is
  the DB row's integer id (or a string form of it), this assertion changes
  — update it deliberately, don't chase a stale string format.
- `test_admin_collect_latest_run_past_nine_and_registry_bounded`
  (`tests/test_serving_admin_api.py:1001-1057`) tests the count-based
  pruning this phase removes entirely — replace with tests for the new
  90-day terminal-only retention (Design §4) and the numeric-recency
  ordering concern the old test's name references should be re-proven
  against whatever now determines "most recent" (the DB's own
  `started_at`/`id` ordering, not string parsing) — the *intent* (don't
  regress to lexical `"collect-9"` vs `"collect-10"` ordering bugs)
  carries forward even though the mechanism doesn't.
- New tests needed (none of this exists today, confirmed by recon): a
  concurrent-start race producing one `202` and one `409`; an unrecognized
  `run_id` producing `404`; heartbeat/lease-expiry recovery on simulated
  restart; retention correctly sparing active rows.

## Scope boundaries

**In scope:** the migration, `CollectionRunWorkflow`, the `admin_collect`/
`admin_collect_status` route changes, startup lease recovery, 90-day
terminal retention, and the test rewrites/additions above.

**Out of scope (Phase 4b or later):** anything under `/v1/admin/sources/*`,
`SourceRepository` batching, file locking, YAML atomic writes — all
Phase 4b. `WorkflowStageAttempt` usage (this phase's runs are single-stage;
per-stage attempt tracking isn't needed here and stays unused, matching
its current state). Renaming `run_type` to `kind` or restructuring
`run_metadata` into `requested_payload`/`summary` columns to match ADR-0006
exactly — the operator's decision was to extend the existing schema
pragmatically, not chase full ADR parity; if ADR-0006 needs updating to
reflect what actually got built, that's a docs follow-up, not new schema
work.

## STOP conditions

- If deciding `'completed'` vs `'succeeded'` (rename-with-backfill vs.
  add-as-synonym) turns out to affect any other code path reading
  `workflow_runs.status` beyond what this phase touches — stop and report
  before choosing either option unilaterally; check for other readers
  first (recon found none outside this phase's own new code, but this
  spec's own recon predates the migration, so re-check at implementation
  time).
- If `admin_collect`'s existing background-thread dispatch mechanism turns
  out to have a subtlety not covered by "the DB row exists before dispatch
  starts" (e.g. it currently does something with `_admin_run_lock` beyond
  simple mutual exclusion that this migration would silently drop) — stop
  and report, don't assume the simplification is safe without re-reading
  the current dispatch code path in full at implementation time.
- If no existing startup-hook pattern exists in `serving/` to call
  `recover_expired_leases()` from — stop and report rather than inventing
  a new app-lifecycle mechanism speculatively.

## Done criteria

- [ ] `workflow_runs` migration merged, additive, matches every prior
      Phase 3 migration's own safety bar (upgrade/downgrade round-trip
      tested against a scratch copy of the real dev DB). Implemented and
      round-trip tested (revision `84cf98a379c1`) — left unchecked because
      it is not yet merged (branch `feat/phase-4a-collection-run-workflow`,
      operator review pending, per this program's process).
- [x] Two concurrent `POST /v1/admin/collect` calls yield exactly one
      `202` and one `409` with the existing run's id. Proven by
      `test_admin_collect_concurrent_start_yields_one_202_one_409`.
- [x] `GET /v1/admin/collect/status?run_id=<unknown>` returns `404`, never
      substitutes the latest run. Proven by
      `test_admin_collect_status_unknown_run_id_returns_404_not_latest`.
- [x] A simulated process restart with a `running`-but-stale row recovers
      it to `interrupted` at next startup, deterministically (not
      timer-dependent). Proven by
      `test_admin_collect_restart_recovers_stale_running_row_to_interrupted`
      through a real FastAPI `lifespan` startup, not by calling the
      workflow method directly.
- [x] Terminal rows older than 90 days are pruned; active
      (`queued`/`running`) rows of any age are never pruned — proven by a
      test, not just code inspection. `tests/unit/storage/test_prune_workflow_runs.py`.
- [x] All module-global run state (`_admin_runs` and friends) is deleted,
      not dual-written alongside the DB. Confirmed via `hasattr` smoke
      test against the imported `api` module.
