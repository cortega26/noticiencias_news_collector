# Todo: Refinery GUI — Phase 4 (parity gaps)

Status: `[ ]` pending · `[x]` done · `[~]` in progress

## Repository method

- [x] `SourceRepository.delete_source(source_id)` — drop sources row

## Contracts (contracts/admin.py)

- [x] `AdminBulkResetRequest` + `AdminBulkResetResult`
- [x] `AdminImageBriefUpdate` + `AdminImageBriefUploadResult`

## API endpoints

- [x] `DELETE /v1/admin/content/{refinery_id}` (reset_one_article)
- [x] `POST /v1/admin/content/bulk-reset` (run_bulk, per-item result)
- [x] `PUT /v1/admin/images/{slug}` (edit brief)
- [x] `POST /v1/admin/images/{slug}/upload` (multipart stage_upload)
- [x] `DELETE /v1/admin/sources/{source_id}` (yaml + DB)

## API tests

- [x] unpublish single + 404
- [x] bulk reset per-item succeeded/failed
- [x] image brief PUT round-trip + 422
- [x] image upload staged asset + status flip
- [x] source delete (yaml + DB) + 404

## GUI

- [x] Client: new api.ts functions + types + vitest
- [x] Content page: Unpublish per row + bulk reset with selection
- [x] Images page: edit form + file upload
- [x] Sources page: Delete action with confirm

## Validation

- [x] Backend gates: lint, type, test, test-contracts, test-boundaries
- [x] Admin gates: admin-test, admin-build
- [x] Live browser e2e
- [x] Commit + push
