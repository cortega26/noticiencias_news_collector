# Todo: Refinery GUI — Phase 3 (operational surface)

Status: `[ ]` pending · `[x]` done · `[~]` in progress

## Repository methods (narrow additions)

- [x] `ArticleRepository.reset_article_for_reprocess(article_id)` — status→pending, clear error
- [x] `SourceRepository.set_source_active(source_id, active)` — flip is_active

## API endpoints (serving/api.py + contracts)

- [x] `POST /v1/admin/collect` + `GET /v1/admin/collect/status` (async job, thread-safe registry)
- [x] `POST /v1/admin/articles/{id}/reprocess`
- [x] `GET /v1/admin/sources` (list + circuit state)
- [x] `POST /v1/admin/sources/{id}/toggle` + `POST /v1/admin/sources/{id}/reset`
- [x] `POST /v1/admin/config` (validated save)
- [x] `GET/POST /v1/admin/prompts` (yaml round-trip)
- [x] `GET /v1/admin/content` + `DELETE /v1/admin/content/{refinery_id}`
- [x] `GET /v1/admin/images` (brief queue)

## API tests (tests/test_serving_admin_api.py)

- [x] collect lifecycle (202 → status transitions, stubbed create_system)
- [x] reprocess reset + 404
- [x] source toggle/reset round-trip
- [x] config save round-trip + invalid → 422
- [x] prompts round-trip on tmp file
- [x] content snapshot + images on seeded dirs

## GUI

- [x] Client: new api.ts functions + types + vitest
- [x] Triage: "Fetch fresh news" button + dry-run toggle + polling + auto-refresh
- [x] Article detail: Reprocess action
- [x] Sources page: toggle + reset actions
- [x] Config page: editor + save
- [x] New pages: /prompts, /content, /images
- [x] Sidebar nav additions

## Validation

- [x] Backend gates: lint, type, test, test-contracts, test-boundaries
- [x] Admin gates: admin-test, admin-build
- [x] Live browser e2e (extended smoke)
- [x] Commit + push
