# Plan 060 / Phase 4c todo — Publication run workflow + Astro "Refine & Publish"

Execution index for [`spec.md`](spec.md). spec.md is binding.

## Migration

- [x] `alembic/versions/e3f168a66d38_workflow_runs_one_active_publication.py`
      — partial unique index, additive, idempotent, down-rev `84cf98a379c1`.
- [x] Matching `Index(...)` in `WorkflowRun.__table_args__`.
- [x] Round-trip verified against a `create_all` DB (downgrade drops it,
      re-upgrade recreates it).
- [x] `tests/test_database_migrations.py`: added to `ALL_REVISIONS` +
      `REVISIONS_WITH_SUPPORTED_DOWNGRADE`; new
      `test_workflow_runs_one_active_publication_index_is_independent_of_collection`.
- [x] `tests/unit/storage/test_migration_guard.py::HEAD_REVISION` bumped.

## Workflow

- [x] `_run_metadata.py` — `json_safe` extracted; `collection_run_workflow`
      imports it (local `_json_safe` removed).
- [x] `publication_run_workflow.py` — `start`/`_run`/`_collect_publication_summary`/
      `_read_latest_attempt`/`get_status`/`recover_expired_leases`/CAS
      transitions; `fail()` stores the summary.
- [x] `tests/unit/logic/workflows/test_publication_run_workflow.py` — 10
      tests: id/url validation, single-flight 409, collection independence,
      `_run` → succeeded (pr_url from attempt), `_run` → failed keeps
      reason, DB-survives-the-run guard, lease recovery scoping, 404-not-latest,
      `_read_attempt_for_id` tracks `RefineryEngine._safe_publication_artifact_name`.
- [x] `_read_attempt_for_id` calls `RefineryEngine._safe_publication_artifact_name`
      directly (was a duplicated regex that could silently drift from the writer).
- [x] `test_refinery_main_accepts_every_kwarg_run_passes` — signature-drift
      guard for the `apps.refinery.main.main` call `_run` makes (the `_run`
      tests fake it with `lambda **kw`, which would swallow a renamed param).

## HTTP

- [x] `AdminPublishRequest`/`AdminPublishStarted`/`AdminPublishStatus` +
      `publishable`/`export_score` on `AdminArticleListItem` in
      `contracts/admin.py`.
- [x] `POST /v1/admin/publish`, `GET /v1/admin/publish/status`,
      `_lifespan` recovery, workflow construction in `serving/api.py`.
- [x] `load_export_candidate_scores()` + `publishable` wiring in the
      articles list route.
- [x] `tests/test_serving_admin_api.py` — 6 tests: 422 id/url combo,
      lifecycle + db-survives, concurrent 202/409, status 404, publishable flag.

## Frontend (`apps/admin`)

- [x] `types.ts` + `api.ts` (`startPublish`, `getPublishStatus`).
- [x] `triage.astro` — URL box, per-card "Refine & publish" button (rendered
      only on `publishable` queue cards), `#publish-status` polling panel,
      `publishInFlight`.
- [x] `src/lib/api.test.ts` — 5 tests (id-only/url-only body, 409→Conflict,
      502→Network, status path).

## Verification

- [x] `pytest` migrations + workflows + serving-admin: 195 passed.
- [x] `pytest -k "workflow or serving or admin or migration or ... contract"`: 669 passed.
- [x] full `pytest tests/`: **2083 passed, 5 skipped** (0:06:29) — includes
      the sanitiser fix and the 3 new Phase-4a-regression guards (P1 real-
      shutdown + P2 signature-drift tables for both workflows).
- [x] `ruff` / `black` / `isort` clean repo-wide; `mypy` adds no new errors
      (pre-existing errors in ai_editor / frontend_publication_validation /
      refinery_engine unchanged).
- [x] `apps/admin`: `npm run check` (0), `npm test` (33), `npm run build` OK.
- [x] Live (real serving API, real `apps.refinery.main.main`, no PR opened —
      bogus id → noop): `POST /v1/admin/publish` → 202; concurrent → 409 with
      the active run's id; polled to terminal `failed` with a clean message;
      `/v1/admin/{articles,config,sources/health}` stayed **200** during and
      after (no Phase 4a regression); unknown run_id → 404; noop summary has
      no stale-file contamination (the `_read_attempt_for_id` exact-match fix).
- [ ] Live with `GITHUB_TOKEN` + a real candidate → PR actually opened
      (needs operator creds; not run here).

## Docs

- [x] `plans/060/phase-4c-publication-run-workflow/spec.md` + this file.
- [ ] `spec-refinery-gui.md` parity note; `AGENTS.md` / `README` if a `make`
      target is added.
