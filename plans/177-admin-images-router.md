# Plan 177: Extract the admin images router (060 Phase 7, first bounded domain)

> Execute step by step; run every verification; stop on STOP conditions.
> **Drift check**: `git diff --stat 145b6147..HEAD -- news_collector/serving/api.py news_collector/serving/admin_images.py tests/test_serving_admin_api.py apps/admin/openapi.json`

## Status

- **Priority**: P2 (060 Phase 7)
- **Effort**: M
- **Risk**: MEDIUM (HTTP wire + generated OpenAPI must not change)
- **Depends on**: 168/169 (images routes), 080 Phase 2 (OpenAPI gate)
- **Category**: serving decomposition
- **Planned at**: commit `145b6147`, 2026-10-20

## Why this matters

`news_collector/serving/api.py` is ~2,955 lines with 35 admin routes inside
`create_app`. Phase 7 calls for splitting route registration by bounded domain
routers after wire characterization. This plan extracts the **images** domain
(3 routes, self-contained: `GET /v1/admin/images`, `PUT /v1/admin/images/{slug}`,
`POST /v1/admin/images/{slug}/upload`) as the pilot; the pattern can then be
repeated for sources/config/analytics/etc. No wire or behaviour change.

## Current state

- `api.py:2590-2730` — the three image routes, using `ImageBriefStore`,
  `AdminImageBriefItem`/`AdminImageQueueEnvelope`/`AdminImageBriefUpdate`/
  `AdminImageBriefUploadResult`, `ImageOrigin`, `MAX_UPLOAD_BYTES`,
  `_read_upload_capped`, `verify_admin_token`.
- `api.py:266-267` — `MAX_UPLOAD_BYTES`/`_UPLOAD_CHUNK_BYTES`;
  `api.py:347-360` — `_read_upload_capped`. **Only the image upload uses them.**
- `tests/test_serving_admin_api.py:2726` monkeypatches
  `serving_api.MAX_UPLOAD_BYTES`; `:2745` imports `_read_upload_capped` from
  `api`. Both must move to the new module.
- `apps/admin/openapi.json` + generated TS are committed and gated by
  `make admin-contracts-check` (operationIds/paths/response models must not
  change).
- The admin tests (`make test-contracts`, `tests/test_serving_admin_api.py`)
  characterize the wire responses.

## Design

- New `news_collector/serving/admin_images.py`:
  - move `MAX_UPLOAD_BYTES`, `_UPLOAD_CHUNK_BYTES`, `_read_upload_capped`;
  - `def build_router(verify_admin_token: Callable[..., None]) -> APIRouter:`
    defines the three routes with the **same function names**
    (`admin_image_queue`, `admin_update_image_brief`,
    `admin_upload_image_brief`) and the same paths/models/status/errors,
    using `Depends(verify_admin_token)`, and returns the router.
  - The factory parameter avoids an `api.py` ↔ `admin_images.py` import cycle.
- `api.py`: import `build_router`, call
  `app.include_router(build_router(verify_admin_token))` inside `create_app`
  (after the dependency is defined), and delete the moved code. Keep the
  module-level names `verify_admin_token`, `create_app`, etc. unchanged.
- The upload route must read `MAX_UPLOAD_BYTES` **at request time** from the new
  module, so the monkeypatch keeps working (patch target changes).

## Steps

1. Create `admin_images.py`; move the constant/chunk size/reader and the three
   routes verbatim (same decorators, models, defaults, status codes, messages,
   docstrings).
2. Wire the router in `api.py`; remove the moved blocks/helpers; keep imports
   tidy (no unused).
3. Update the two tests to patch/import the new module
   (`news_collector.serving.admin_images`), keeping the same assertions.
4. Verify:
   - `make admin-contracts-check` — **must pass without regenerating** the
     artifact; if it fails, STOP (the OpenAPI changed).
   - `make test-contracts`, `make test-boundaries`, `make test` (unit),
     `make lint`, `make type` (committed), `make admin-test`,
     `make admin-lint`, `make admin-build`, `make docs-check`,
     `make inventory-refresh && make inventory-check`,
     `make plans-ledger-check`.
   - Focused: `tests/test_serving_admin_api.py` (all image/upload tests).
5. `docs/ARCHITECTURE.md` (or the serving section): one line noting the first
   domain router and the pattern for future splits.
6. `plans/060/todo.md`: note the images pilot (the Phase 7 item stays open for
   the remaining domains).

## Done criteria

- [ ] `admin_images.py` owns the three routes + upload helpers; `create_app` includes it
- [ ] No wire change: `apps/admin/openapi.json` unchanged, `admin-contracts-check` green
- [ ] Same paths, operationIds, response models, status codes and error details
- [ ] Tests updated only for the moved constants/helpers; assertions unchanged
- [ ] Gates green; Phase 7 note updated
- [ ] Ledger row 177 updated by the reviewer

## STOP conditions

- `admin-contracts-check` fails (OpenAPI drift) → report; do not regenerate
  unless the change is an intentional API change (it is not).
- The router factory needs changes to `verify_admin_token`/`create_app`
  semantics → report.
- A test requires changing an expected wire response → STOP.
- Any frontend change is needed → STOP.
