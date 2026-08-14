# Todo: Admin API surface (Phase 1)

Status legend: `[ ]` pending · `[x]` done · `[~]` in progress

## Contract

- [x] `news_collector/contracts/admin.py` — typed models (list item, detail,
      source health reuse, analytics envelope, config snapshot, mutation
      request/result shapes)
- [x] Contract tests: model round-trip / required fields / defaults
      (covered via `tests/test_serving_admin_api.py` response-model validation)

## Serving

- [x] `verify_admin_token` dependency (constant-time, fail-closed, distinct
      `ADMIN_API_KEY`)
- [x] `GET /v1/admin/articles` — status filter + cursor pagination + projection
- [x] `GET /v1/admin/articles/{id}` — detail with ScoreLog + publication/audit state
- [x] `GET /v1/admin/sources/health` — reads collector export artifact
- [x] `GET /v1/admin/analytics` — analytics read model + as_of
- [x] `GET /v1/admin/config` — sanitized allowlist snapshot
- [x] `POST /v1/admin/articles/{id}/audit-status` — dispatch to existing
      `update_article_audit_status`
- [x] `POST /v1/admin/articles/{id}/reject` — dispatch to existing
      `reject_publication_attempts`

## Tests (`tests/test_serving_admin_api.py`)

- [x] Auth fail-closed matrix (503/401/403/200)
- [x] Triage list filtering + payload shape + cursor traversal
- [x] Detail (full row + ScoreLog + state) + 404
- [x] Source health (seeded file, missing file)
- [x] Analytics envelope + as_of
- [x] Config allowlist (planted secret absent)
- [x] Mutations (audit-status idempotent, reject noop for already-rejected)

## Docs & env

- [x] `docs/PIPELINE_CONTRACTS.md` — admin surface entry
- [x] `.env.example` — `ADMIN_API_KEY` documented

## Validation

- [x] `make lint`
- [x] `make type`
- [x] `make test-contracts`
- [x] `make test-boundaries`
- [x] `pytest tests/test_serving_admin_api.py -q` (20/20)
- [x] `make test` (full unit suite, zero warnings)
- [x] `make docs-check`
