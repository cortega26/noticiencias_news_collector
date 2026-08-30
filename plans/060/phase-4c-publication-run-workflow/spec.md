# Plan 060 / Phase 4c — Publication run workflow + Astro "Refine & Publish"

## Why this phase exists

Publication to noticiencias.com is human-driven: an editor picks a scored
candidate article (or pastes a URL), the Refinery rewrites it and opens a PR
against the `noticiencias` frontend repo, and the editor merges it. That
"pick + publish" step existed **only in the Streamlit panel**
(`apps/refinery/admin_panel.py` → "Operaciones del Pipeline" → "✨ Refinar y
Publicar" → `apps.refinery.main.main(process_id=…)`).

The new Astro admin (`apps/admin/`) had triage, images, live-CMS, analytics,
sources, prompts, config, and collect — but no way to publish. The migration
off Streamlit cannot complete without it. The daily CI (`daily_collector.yml`)
only runs the collector; it never publishes. This is the one missing
load-bearing feature.

This phase is a direct sibling of Phase 4a (`CollectionRunWorkflow`): a
durable, single-flight `PublicationRunWorkflow`, a thin HTTP surface, and a
publish action in the triage UI.

## Decisions (operator, 2026-08-29)

- **Scope:** the publish feature only. Remaining minor Streamlit-only gaps
  (system-logs viewer, factory reset) are a separate follow-up.
- **UI placement:** a per-card "Refine & publish →" button in the `/triage`
  queue, shown only on cards whose article is a publish candidate
  (`publishable`), + a "Publish from URL" box at the top of `/triage`.
  (An earlier build put the button in the detail panel; moved to the cards
  per the operator on 2026-08-29 to match the original plan.)
- **Backend:** wrap `apps.refinery.main.main(process_id=…/article_url=…)`.
  In `process_id` mode `main()` skips the collector and builds its **own**
  `DatabaseManager()` (`apps/refinery/main.py:448`) — it never closes the
  process-wide singleton the serving API holds, so the Phase 4a
  `system.shutdown()` defect cannot recur through this path. Reusing the
  battle-tested wrapper keeps the target-repo clone / editor / auditor / PR
  logic in one place.

## Design

### 1. Migration — `e3f168a66d38_workflow_runs_one_active_publication`

Purely additive: one partial unique index, mirroring
`uq_workflow_runs_one_active_collection` but scoped to `run_type='publication'`:

```
uq_workflow_runs_one_active_publication
  UNIQUE (run_type) WHERE run_type = 'publication'
                      AND status IN ('queued', 'running')
```

No columns, no constraint changes (`run_type` is free-form `String(50)`,
`ck_workflow_runs_status` already allows all six values). Index added to
`WorkflowRun.__table_args__` (`news_collector/storage/models.py`).
Down-revision `84cf98a379c1`. Round-trip tested; `test_database_migrations.py`
`REVISIONS_WITH_SUPPORTED_DOWNGRADE` and `test_migration_guard.HEAD_REVISION`
updated.

### 2. `news_collector/logic/workflows/publication_run_workflow.py` (new)

Near-copy of `collection_run_workflow.py` — same durable/lease/recovery CAS
pattern, same typed frozen-dataclass results. `_json_safe` extracted to
`news_collector/logic/workflows/_run_metadata.py` (`json_safe`) and shared
by both workflows.

- `start(*, article_id: int | None, article_url: str | None, dry_run=False)`
  — exactly one of id/url required (else typed `invalid_request` → HTTP 422);
  inserts a `run_type='publication'` queued row; the new partial index
  yields the typed `already_running` result (→ 409) if a publication run is
  active; dispatches `_run` on a daemon thread.
- `_run` — heartbeat thread, then
  `apps.refinery.main.main(process_id=str(article_id) | None, article_url=…,
  skip_visuals=False, dry_run=…)` (blocking; fine on the daemon thread).
  `success` + `processed_count > 0` → `complete()`; otherwise `fail()`
  **with the summary** (an editorial/auditor rejection is a `failed` run the
  operator still needs the reason for).
- `_collect_publication_summary` — merge `main()`'s result dict with the
  persisted `PublicationAttemptSummary`
  (`data/runtime/publication_attempts/{id}.json`, contract
  `news_collector/contracts/publication_validation.py` — `pr_url`,
  `branch_name`, `final_slug`, `failure_class`, `stages`). Run through
  `json_safe` before persisting into `run_metadata.summary`.
- `get_status` / `recover_expired_leases` — identical to the collection
  workflow, scoped to `run_type='publication'`.

### 3. HTTP layer — `news_collector/serving/api.py` (thin wrapper only)

- `POST /v1/admin/publish` — body `AdminPublishRequest`
  `{article_id?, article_url?, dry_run?}` → 202 `{run_id, status, detail}`;
  409 (typed body with the active run's id); 422 for a bad id/url combo.
- `GET /v1/admin/publish/status?run_id=` — the exact row or 404 (never
  latest). `AdminPublishStatus` surfaces `pr_url` / `failure_class` /
  `final_slug` pulled from `run_metadata.summary`.
- `_lifespan` also calls `publication_run_workflow.recover_expired_leases()`.
- `PublicationRunWorkflow(db_manager)` constructed next to the collection one.
- `load_export_candidate_scores()` reads `data/exports/latest_articles.json`
  (`_EXPORT_ARTIFACT_PATH`, module-level, test-patchable) → `{id: score}`.
  `_build_admin_list_item` sets `publishable = id in export
  AND processing_status not in {publishing, completed, rejected}` and
  `export_score`. Contracts `AdminArticleListItem.publishable/export_score`
  added; retention prune (`scripts/ops/prune_workflow_runs.py`) is already
  run_type-agnostic — no change.

### 4. Frontend — `apps/admin/`

- `api.ts`: `startPublish({articleId?, articleUrl?, dryRun?})`,
  `getPublishStatus(runId)`. `types.ts`: `AdminPublishStarted`,
  `AdminPublishStatus`, + `publishable`/`export_score` on
  `AdminArticleListItem`. Reuses `ConflictError` (409) and the
  502/503/504→`NetworkError` mapping.
- `triage.astro`: "Publish from URL" form above the queue; a per-card
  "Refine & publish →" button rendered only on queue cards whose item is
  `publishable`; a `#publish-status` polling panel reusing
  `pollCollect`'s pattern (incl. the `MAX_TRANSIENT` NetworkError
  tolerance). `succeeded` → PR link; `failed` → `failure_class` + reason,
  read as an outcome not an error; a `publishInFlight` flag disables both
  entry points during a run.

## Constraints / notes

- **Single-flight is global** (one publish at a time) — the Refinery clones
  the target repo into a shared dir and pushes; concurrent runs corrupt
  each other. The collection and publication guards are independent.
- **Publish-by-id needs the article in the current export.** Articles not
  in `latest_articles.json` are published via the URL box. Same constraint
  the Streamlit flow lives with.
- **`GITHUB_TOKEN` must be in the serving process env** for PR creation
  (`config.github.token`) — runbook note.
- **SQLite**: `main()`'s own `DatabaseManager` is a second connection to the
  same file during a run. Single-flight + the API being mostly reads keeps
  contention negligible; this is exactly how the Streamlit panel already
  runs `run_refinery` in-process.

## Done criteria

- [ ] Migration merged, additive, round-trip tested; a second active
      `publication` row is rejected, a `collection` row is unaffected.
- [ ] `POST /v1/admin/publish` → 202/409/422; `GET /v1/admin/publish/status`
      unknown id → 404, never latest.
- [ ] A publish run reaches `succeeded` with `pr_url` surfaced, and a
      follow-up `/v1/admin/*` request still returns 200 (Phase 4a
      regression guard).
- [ ] An auditor/editorial block is a `failed` run whose reason
      (`failure_class` + message) is preserved and shown.
- [ ] Stale `running` `publication` rows recover to `interrupted` at
      startup, deterministically.
- [ ] `publishable` is True only for pending articles in the current export.
- [ ] `make test` / `make type` green; `apps/admin` `check`/`test`/`build`
      green.

## Out of scope

- `/config` system-logs viewer (Streamlit "Settings & Logs").
- Factory reset ("Reinicio de Fábrica").
- Standalone URL-ingest-to-inbox (folded into "Publish from URL").
