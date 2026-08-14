# Spec: Refinery GUI — Phase 3 (operational surface)

## Goals

Phase 2 delivered the read + triage surface. Phase 3 adds the **operational**
capabilities the GUI is missing — everything that writes, runs, or manages:
fetch fresh news, reprocess, source management, config editing, prompt lab,
published-content (Live CMS) snapshot/reset, and the image queue. Same
governance discipline as Phase 1: serving dispatches to existing storage/
workflow functions; no new write logic authored in serving.

Success criteria:

1. Every missing Streamlit-tab capability maps to one or more admin
   endpoints; the GUI gains the corresponding views/actions.
2. Long-running operations (collection) are async: POST returns 202 + a
   run id; a status endpoint reports queued/running/succeeded/failed.
3. Mutations dispatch to existing modules only:
   - collect → `create_system` + `run_collection_cycle` (+ export)
   - reprocess → reset article status to pending (new repository method)
   - source toggle/reset → `SourceRepository` circuit-state transitions
   - config save → `save_config` (config_manager) with validation
   - prompts → read/write `config/prompts.yaml`
   - content reset → `reset_one_article` (published_content)
   - image queue → `ImageBriefStore.list_briefs` (read-only)
4. GUI: nav gains Operations, Sources (manage), Prompts, Content, Images;
   triage header gains "Fetch fresh news" with status polling + auto-refresh.

## Endpoints (all under `/v1/admin`, all `Depends(verify_admin_token)`)

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/collect` | POST | Start collection cycle (dry_run flag optional) | `create_system().initialize()` + `run_collection_cycle` in a background thread; returns run_id |
| `/v1/admin/collect/status` | GET | Poll the last/any run | in-memory run registry (module-level, thread-safe) |
| `/v1/admin/articles/{id}/reprocess` | POST | Reset article to pending for re-running | new `ArticleRepository.reset_article_for_reprocess` |
| `/v1/admin/sources` | GET | All sources + circuit state + config-derived metadata | `SourceRepository.get_source_circuit_state` per source + `ALL_SOURCES` |
| `/v1/admin/sources/{id}/toggle` | POST | Activate/deactivate a source (is_active) | new `SourceRepository.set_source_active` |
| `/v1/admin/sources/{id}/reset` | POST | Clear circuit breaker (force ACTIVE) | `update_source_circuit_state(success=True)` |
| `/v1/admin/config` | POST | Validate + save config.toml | `load_config` + `save_config` (config_manager) |
| `/v1/admin/prompts` | GET | Read `config/prompts.yaml` | yaml read (allowlist of top-level keys) |
| `/v1/admin/prompts` | POST | Write prompts.yaml (validated dict) | yaml dump, atomic |
| `/v1/admin/content` | GET | Published content snapshot | `resolve_published_content_snapshot` (read) |
| `/v1/admin/content/{refinery_id}` | DELETE | Reset a published article (git + DB) | `reset_one_article` (published_content) |
| `/v1/admin/images` | GET | Image brief queue | `ImageBriefStore.list_briefs` |

### Collect job semantics

- `POST /v1/admin/collect {dry_run: bool}` → starts a daemon thread:
  `create_system(config_override)` → `initialize()` → asyncio
  `run_collection_cycle(dry_run)` → (non-dry) `export_latest_articles`.
  Registers `{run_id, status, started_at, finished_at, error, summary}`.
- `GET /v1/admin/collect/status` → latest run + active flag.
- No new abstraction class: a module-level dict guarded by a `threading.Lock`
  (the plan 038 metrics store already proves this pattern in the repo).

### New repository methods (narrow, existing classes only)

1. `ArticleRepository.reset_article_for_reprocess(article_id) -> bool` —
   sets `processing_status="pending"`, clears `error_message`,
   `processing_status` audit metadata reset.
2. `SourceRepository.set_source_active(source_id, active) -> bool` —
   flips `is_active` (keeps circuit state intact).

### GUI views

- **Triage header**: "Fetch fresh news" button (+ dry-run toggle) →
  POST collect → poll status every 2s → toast on completion → reload queue.
- **Sidebar**: Sources → `/sources` gains toggle + reset-circuit actions;
  new pages `/prompts`, `/content`, `/images`.
- **Config** page gains an editor (JSON form) + save button with validation
  errors surfaced.
- **Article detail**: "Reprocess" action button.

### Explicitly out of scope (documented)

- Deploying the GUI (hosting decision after acceptance).
- Removing the Streamlit app (parity then removal).
- Secrets editing via the GUI (config save excludes secret fields; env
  overrides stay in `.env`).
- Cross-repo publishing (PR creation) — remains in workflow/CLI.

## Verification

1. API tests in `tests/test_serving_admin_api.py` (extended):
   - collect POST → 202 + run_id; status transitions queued→running→succeeded
     (with a stubbed collection function via monkeypatch of create_system).
   - reprocess resets status to pending; 404 unknown id.
   - source toggle/reset round-trip on seeded Source rows.
   - config POST: valid save round-trip; invalid → 422 with detail.
   - prompts GET/POST round-trip on a tmp prompts.yaml (monkeypatch path).
   - content snapshot + image list on seeded tmp dirs.
2. GUI: vitest additions for the new client functions (mocked fetch).
3. Live browser e2e (extended smoke): fetch button triggers a dry-run
   collect (dry_run keeps it fast and side-effect-free), status completes,
   queue refreshes; sources toggle reflects; config save round-trip.
4. `make lint`, `make type`, `make test`, `make test-contracts`,
   `make test-boundaries`, `make admin-test`, `make admin-build`.

Change class: serving + storage + GUI → High: baseline + contract/boundary
gates + targeted tests.
