# Todo: Refinery GUI — Phase 3 (operational surface)

Status: `[ ]` pending · `[x]` done · `[~]` in progress

## Repository methods (narrow additions)

- [ ] `ArticleRepository.reset_article_for_reprocess(article_id)` — status→pending, clear error
- [ ] `SourceRepository.set_source_active(source_id, active)` — flip is_active

## API endpoints (serving/api.py + contracts)

- [ ] `POST /v1/admin/collect` + `GET /v1/admin/collect/status` (async job, thread-safe registry)
- [ ] `POST /v1/admin/articles/{id}/reprocess`
- [ ] `GET /v1/admin/sources` (list + circuit state)
- [ ] `POST /v1/admin/sources/{id}/toggle` + `POST /v1/admin/sources/{id}/reset`
- [ ] `POST /v1/admin/config` (validated save)
- [ ] `GET/POST /v1/admin/prompts` (yaml round-trip)
- [ ] `GET /v1/admin/content` + `DELETE /v1/admin/content/{refinery_id}`
- [ ] `GET /v1/admin/images` (brief queue)

## API tests (tests/test_serving_admin_api.py)

- [ ] collect lifecycle (202 → status transitions, stubbed create_system)
- [ ] reprocess reset + 404
- [ ] source toggle/reset round-trip
- [ ] config save round-trip + invalid → 422
- [ ] prompts round-trip on tmp file
- [ ] content snapshot + images on seeded dirs

## GUI

- [ ] Client: new api.ts functions + types + vitest
- [ ] Triage: "Fetch fresh news" button + dry-run toggle + polling + auto-refresh
- [ ] Article detail: Reprocess action
- [ ] Sources page: toggle + reset actions
- [ ] Config page: editor + save
- [ ] New pages: /prompts, /content, /images
- [ ] Sidebar nav additions

## Validation

- [ ] Backend gates: lint, type, test, test-contracts, test-boundaries
- [ ] Admin gates: admin-test, admin-build
- [ ] Live browser e2e (extended smoke)
- [ ] Commit + push
