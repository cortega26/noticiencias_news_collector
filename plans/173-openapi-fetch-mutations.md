# Plan 173: Migrate the admin JSON mutations to the typed client

> Execute step by step; run every verification; stop on STOP conditions.
> **Drift check**: `git diff --stat c2a2f07a..HEAD -- apps/admin/src/lib/api.ts apps/admin/src/lib/api.test.ts apps/admin/src/lib/generated/api.d.ts`

## Status

- **Priority**: P2 (060 Phase 6 — completes the client adoption for JSON calls)
- **Effort**: M
- **Risk**: MEDIUM (409/422 bodies, nulls, arbitrary patch bodies)
- **Depends on**: 171 (client), 172 (reads)
- **Category**: admin client / typed contracts
- **Planned at**: commit `c2a2f07a`, 2026-10-20

## Why this matters

Reads are on `openapi-fetch`; the JSON mutations still hand-build paths and
bodies. Migrating them removes the last string paths from the admin runtime
client and makes request/response shapes compile-checked. The **multipart
upload stays on `apiFetch`** (special body; out of scope) and is documented as
the one remaining exception.

## Current state

- `apps/admin/src/lib/api.ts` — `readContract<T>` (reads) and `apiFetch<T>`
  (mutations + multipart upload).
- JSON mutations to migrate, with their current wire:
  - `rejectArticle(id, reason)` — POST `/v1/admin/articles/{id}/reject` `{reason}`
  - `updateAuditStatus(id, status, reason)` — POST `.../audit-status` `{audit_status, reason}`
  - `startCollect(dryRun)` — POST `/v1/admin/collect` `{dry_run}`
  - `startPublish({articleId?, articleUrl?})` — POST `/v1/admin/publish` `{article_id, article_url}` (nulls when absent)
  - `startPublishBatch(ids)` — POST `/v1/admin/publish/batch` `{article_ids}`
  - `reprocessArticle(id)` — POST `.../reprocess` `{}`
  - `toggleSource(sourceId, active)` — POST `/v1/admin/sources/{id}/toggle` `{active}`
  - `resetSourceCircuit(sourceId)` — POST `.../reset` `{}`
  - `saveConfig(patch)` — POST `/v1/admin/config` (arbitrary object)
  - `savePrompts(prompts)` — POST `/v1/admin/prompts` `{prompts}`
  - `bulkResetContent(ids)` — POST `/v1/admin/content/bulk-reset` `{refinery_ids}`
  - `updateImageBrief(slug, fields)` — PUT `/v1/admin/images/{slug}` `fields`
  - `unpublishArticle(refineryId)` — DELETE `/v1/admin/content/{refinery_id}`
  - `deleteSource(sourceId)` — DELETE `/v1/admin/sources/{source_id}`
  - `upsertSource(payload)` — POST `/v1/admin/sources`
- Error taxonomy/middleware from 171; 409 must keep carrying the parsed body
  (`ConflictError`) for `startCollect`/`startPublish`/`startPublishBatch`.

## Scope

**In scope**: `apps/admin/src/lib/api.ts` (JSON mutations only),
`apps/admin/src/lib/api.test.ts` (or a focused test), `plans/060/todo.md`
(Phase 6 note; the checkbox can be closed only if every JSON mutation is
migrated and the multipart exception is documented — otherwise leave it open).

**Out of scope**: `uploadImageBriefAsset` (multipart), `apiFetch` semantics,
generated artifacts, backend code, the frontend repo.

## Rules

- Keep signatures and return types unchanged.
- Request bodies must be **byte-identical** for the same arguments (including
  `null` vs omitted in `startPublish`, `{}` bodies, and the arbitrary config
  patch). If a generated body type is narrower, use a documented cast on the
  body; never change the wire.
- 409/422 behaviour must stay: `ConflictError` with the parsed body for the
  run-starting endpoints, `ValidationError` for 422, `AuthError` for 401.
- DELETE/204-style responses: if the endpoint returns no body, type it as the
  existing return (`AdminMutationResult`) only if the server sends one; verify
  the generated response and the current behaviour before casting.

## Steps

1. Confirm each generated path/method/body name; list any mismatch (STOP if it
   would change the wire).
2. Migrate in this order: `rejectArticle`, `updateAuditStatus`,
   `reprocessArticle`, `toggleSource`, `resetSourceCircuit`, `saveConfig`,
   `savePrompts`, `bulkResetContent`, `updateImageBrief`, `unpublishArticle`,
   `deleteSource`, `upsertSource`, `startCollect`, `startPublish`,
   `startPublishBatch`.
3. Tests: per endpoint, assert method/path/JSON body (exact), Bearer header,
   and parsed success; add 409 (`startCollect`/`startPublish`/batch) and 422
   cases asserting the same classes/bodies; keep every existing test.
4. `plans/060/todo.md`: record the JSON-mutation batch and the multipart
   exception; decide the checkbox honestly (leave open if the upload remains).
5. Gates: `make admin-test`, `make admin-lint`, `make admin-build`,
   `make admin-contracts-check`, `make lint`, `make type` (committed),
   `make test`, `make test-boundaries`,
   `make inventory-refresh && make inventory-check`, `make plans-ledger-check`.

## Done criteria

- [ ] All JSON mutations use the typed client; signatures/returns unchanged
- [ ] Wire bodies/paths identical (tests), 409/422/401 behaviour preserved
- [ ] Multipart upload unchanged and documented as the exception
- [ ] Admin/backend gates green; Phase 6 note updated honestly
- [ ] Ledger row 173 updated by the reviewer

## STOP conditions

- A generated body type would force a wire change (e.g. omit a `null` the
  server expects) → report.
- A DELETE/204 endpoint's current return depends on `apiFetch`'s JSON parse of
  an empty body → report; keep it on `apiFetch`.
- The migration forces changes outside `api.ts`/tests → report.
- Any backend change is needed → STOP.
