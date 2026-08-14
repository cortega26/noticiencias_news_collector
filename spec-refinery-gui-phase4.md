# Spec: Refinery GUI — Phase 4 (parity gaps with the old Streamlit GUI)

## Goals

Close the three remaining functional gaps identified in the parity audit
against `apps/refinery/admin_panel.py`, so the new GUI can replace the
Streamlit app:

1. **Unpublish/reset published articles** (git-backed, per-article and bulk)
   — the old GUI's `reset_one_article` + `run_bulk` flow.
2. **Image brief editing + asset upload** — the old GUI's image-brief form
   with `stage_upload`.
3. **Delete a source** — the old GUI's "Eliminar Fuente" (removes from
   `config/sources.yaml`).

Same governance discipline: serving dispatches to existing modules only;
no new write logic authored in serving. Secrets management stays out of
scope (documented; API never accepts credentials).

## Endpoints (all under `/v1/admin`, all `Depends(verify_admin_token)`)

### 1. Unpublish / reset published content

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/content/{refinery_id}` | DELETE | Unpublish one article (git rm + commit + push + DB delete) | `resolve_published_content_snapshot` + `reset_one_article` |
| `/v1/admin/content/bulk-reset` | POST | Bulk unpublish (batch_cap 5, continue-on-error) | `run_bulk` + `reset_one_article` |

Body for bulk-reset: `{"refinery_ids": [...]}`. Both return a structured
result (per-item succeeded/failed — LAW-B6).

The reset flow requires a writable checkout of the target repo. The endpoint
reuses `resolve_published_content_snapshot` (which finds the local checkout
or clones to `temp/refinery_target`), then runs `reset_one_article` per item
with the configured `github.token` — identical to the old GUI's flow.

### 2. Image brief editing + upload

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/images/{slug}` | PUT | Edit brief fields (topic, news_angle, scientific_domain, subject_scene, draft_alt_text, tone) | `ImageBriefStore.load_brief` + `save_brief` |
| `/v1/admin/images/{slug}/upload` | POST | Stage an image asset (multipart) | `ImageBriefStore.stage_upload` |

Upload accepts `multipart/form-data`: `file` (binary) + the same text
fields. `stage_upload` sets `status=editorial_image_ready`. Both validate
against the `ImageBriefModel` shape (pydantic) — invalid → 422.

### 3. Delete source

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/sources/{source_id}` | DELETE | Remove from `config/sources.yaml` + drop DB row | `ALL_SOURCES` mutation + `save_sources` + `SourceRepository` delete (new) |

New narrow method `SourceRepository.delete_source(source_id) -> bool` —
removes the `sources` table row. The yaml removal reuses `save_sources`
(the exact call the old GUI makes).

## Contracts (add to `news_collector/contracts/admin.py`)

- `AdminBulkResetRequest` — `refinery_ids: List[str]` (min 1, max 50)
- `AdminBulkResetResult` — `succeeded: List[str]`, `failed: List[dict]`
  (`{refinery_id, error}`), `summary: str`
- `AdminImageBriefUpdate` — optional text fields (topic, news_angle,
  scientific_domain, subject_scene, draft_alt_text, tone)
- `AdminImageBriefUploadResult` — the updated brief as dict + `asset_path`
- `AdminMutationResult` reuse for source delete (status ok/not_found)

## GUI views

- **Content page**: each row gains "Unpublish" (DELETE with confirm);
  header gains "Bulk reset (N)" button with checkbox selection.
- **Images page**: each brief card gains "Edit" (inline form) + file input
  "Stage asset"; save → PUT; upload → POST with progress/status.
- **Sources page**: each row gains "Delete" (with confirm — it edits
  sources.yaml).

## Explicitly out of scope (documented)

- Secrets management (GitHub/UI tokens, Gemini/NVIDIA keys) — API never
  accepts credentials; `.env` remains the only place.
- Source *creation/editing* (add/modify source) — the old GUI's source
  editor; defer unless requested (delete is the parity gap named).
- Deploying the GUI; removing the Streamlit app (after parity acceptance).

## Verification

1. API tests (extend `tests/test_serving_admin_api.py`):
   - unpublish: monkeypatch `reset_one_article`/snapshot → DELETE returns
     structured result; unknown id → 404; bulk-reset reports
     succeeded/failed per item (LAW-B6).
   - image brief PUT: round-trip on tmp ImageBriefStore dir; invalid →
     422; upload: multipart file → staged asset exists + status flipped.
   - source delete: yaml entry removed (tmp file) + DB row gone; unknown
     id → 404.
2. GUI: vitest additions for new client functions (mocked fetch).
3. Live browser e2e: content unpublish flow (with a temp target repo),
   image edit+upload round-trip, source delete on a throwaway source.
4. `make lint`, `make type`, `make test`, `make test-contracts`,
   `make test-boundaries`, `make admin-test`, `make admin-build`.

Change class: serving + storage + GUI → High: baseline + contract/boundary
gates + targeted tests.
