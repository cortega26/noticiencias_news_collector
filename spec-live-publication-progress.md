# Spec — live publication progress in the admin GUI

## Context

A single publication run takes ~12 minutes (refine → image → AI editor →
audit → frontend validation → PR). The `/triage` panel polled
`GET /v1/admin/publish/status` every few seconds but always rendered the same
static line ("Procesando… editor → auditoría → imagen → PR"), so an editor
could not tell a healthy run from a hung one. Runs 58 and 60 were killed
mid-flight (uvicorn reload, see the SERVING_RELOAD switch) and the panel gave
no hint; the stale `running` row was only explained by lease recovery.

## Goal

Show, for an in-flight run, **where it is and whether it is still alive** —
advisory only:

1. **Backend** — the status endpoint exposes the article's completed Refinery
   stage names in order, the current item index/count for batch runs, the last
   lease heartbeat, and the median wall time of recent successful
   single-article runs (the ETA baseline).
2. **Frontend** — `/triage` folds those raw stage names into six
   editor-facing phases, ticks an elapsed clock and ETA every second, and
   flags a possible hang when no signal (heartbeat or progress write) has
   arrived for ≥150 s (two missed 60 s heartbeats). The API-unreachable
   retry path keeps the last known panel and annotates it.
3. **Never harmful** — progress is advisory: listener and DB write failures
   are logged and must never alter the publication outcome (LAW-B7).

## Architecture

### Backend

- `news_collector/logic/workflows/refinery_engine.py`
  - `RefineryEngine.stage_listener: Optional[Callable[[str, str, bool], None]]`
  - `_PublicationRun.record_stage` notifies via `_notify_stage(article_id,
    name, success)`; a listener exception is logged (`logger.warning`) and
    swallowed. `_last_publication_stages` behavior is unchanged.
- `news_collector/logic/workflows/publication_pipeline.py`
  - `run_publication_pipeline(..., stage_listener=None)` assigns
    `engine.stage_listener`.
  - `run_publication_batch(..., stage_listener=None, on_item_start=None)`
    forwards the listener per item and calls `on_item_start(index, count,
    article_id)` before each item (0-based index).
- `news_collector/logic/workflows/publication_run_workflow.py`
  - `_stage_listener(run_id)` → `record_progress_stage(run_id, name)`.
  - `_write_progress(run_id, update_fn)` read-modify-writes
    `workflow_runs.run_metadata['progress']` (`stages`, `item_index`,
    `item_count`, `updated_at` UTC ISO); wrapped in try/except + warning.
  - `_reset_progress` clears `stages` and sets item position at the start of
    each article (single and batch).
  - `_typical_seconds(session)` = median of up to the last 10 successful
    single-article runs (batch runs excluded by `summary.mode == "batch"`),
    computed only while the run is queued/running.
  - `PublicationRunStatusResult` gains `progress: dict` and
    `typical_seconds: int | None`; `_as_utc` normalizes naive SQLite
    datetimes.
- `news_collector/contracts/admin.py`
  - New `AdminPublishProgress` (`stages`, `item_index`, `item_count`,
    `updated_at`); `AdminPublishStatus` gains `progress`, `heartbeat_at`,
    `typical_seconds`.
- `news_collector/serving/api.py` — maps the result fields into
  `AdminPublishStatus` (progress validated through the contract model).

### Frontend (`apps/admin`)

- `src/lib/publishProgress.ts` (new, pure, no DOM):
  - `PUBLISH_PHASES` — six phases with the stage whose completion closes
    each one (`identity_resolved`, `image_resolution`, `editor_refinement`,
    `frontmatter_guard`, `frontend_publication_validation`, `pr_created`).
  - `currentPhaseIndex` — one past the furthest marker reached, clamped.
  - `parseServerTime` — naive server timestamps are UTC.
  - `formatDuration`, `describeEta` (remaining vs median × item count),
    `secondsSinceLastSign`, `STALL_AFTER_SECONDS = 150`.
- `src/pages/triage.astro` — skeleton with per-phase bar; `showProgress`
  keeps a 1 s ticker and patches text/classes in place (the CSS sweep never
  restarts); `stopProgress` on completion/auth failure; NetworkError retry
  annotates the panel instead of replacing it; `pp-stalled` when heartbeat
  and progress are both quiet or the API is out of reach.
- `openapi.json` + `src/lib/generated/api.d.ts` regenerated from the
  backend contract (`make admin-contracts-generate`).

## Files

- `news_collector/contracts/admin.py`
- `news_collector/logic/workflows/refinery_engine.py`
- `news_collector/logic/workflows/publication_pipeline.py`
- `news_collector/logic/workflows/publication_run_workflow.py`
- `news_collector/serving/api.py`
- `apps/admin/src/lib/publishProgress.ts` (new)
- `apps/admin/src/lib/publishProgress.test.ts` (new)
- `apps/admin/src/pages/triage.astro`
- `apps/admin/openapi.json`, `apps/admin/src/lib/generated/api.d.ts`
  (generated)
- Tests: `tests/unit/logic/workflows/test_refinery_stage_listener.py` (new),
  `tests/unit/logic/workflows/test_publication_run_workflow.py`,
  `tests/unit/logic/workflows/test_publication_batch.py`

## Acceptance

1. `GET /v1/admin/publish/status?run_id=N` for a running run returns
   `progress.stages` in recorded order, `heartbeat_at`, and
   `typical_seconds`; `progress` is reset per article in batch runs and
   `item_index`/`item_count` track the batch position.
2. `typical_seconds` is the median of ≤10 recent successful single-article
   runs; batch runs never contribute; `null` when there is no history.
3. A raising stage listener or a failing progress DB write never changes the
   publication result (tests assert no exception propagates).
4. Frontend helpers: phase folding ignores unknown/minor stages, naive
   timestamps parse as UTC, ETA scales with batch size, stall detection uses
   the most recent signal (10 unit tests).
5. `make admin-contracts-check` is green (artifact + generated types in
   sync); `make inventory-check` clean after the new files.
6. No cross-repo contract change: the admin app and its generated client are
   in-repo; the publication frontend schema is untouched.

## Verification

- `.venv/bin/python -m pytest tests/unit/logic/workflows/test_refinery_stage_listener.py tests/unit/logic/workflows/test_publication_run_workflow.py tests/unit/logic/workflows/test_publication_batch.py -q --no-cov` — 37 passed.
- `npm --prefix apps/admin exec vitest run src/lib/publishProgress.test.ts` — 10 passed.
- `make admin-contracts-check` — green.
- Gates: `make lint`, `make type`, `make test`, `make test-boundaries`,
  `make test-contracts`, `make admin-test`.
- Inventory: `make inventory-refresh && make inventory-check`.
- Manual smoke (operator): `SERVING_RELOAD=0 make admin`, publish a candidate
  and watch the panel advance; a killed worker should show the stall flag
  after 150 s of silence.

## Risks / notes

- Progress adds one small DB write per recorded stage (~15–20 per article);
  measured as negligible against a ~12 min run, but it is a write on the
  serving path's daemon thread — kept advisory precisely for that reason.
- The listener fires synchronously inside `record_stage`; a future slow
  listener would slow publishing. `_write_progress` is a single short
  transaction and failures are swallowed.
- `STALL_AFTER_SECONDS = 150` assumes the existing 60 s lease heartbeat
  interval; if that constant changes, revisit the frontend constant.
- Panel strings are Spanish (admin UI language); helper logic is
  language-neutral.
