# Plan 172: Migrate the admin read endpoints to the typed `openapi-fetch` client

> Execute step by step; run every verification; stop on STOP conditions.
> **Drift check**: `git diff --stat 64f99891..HEAD -- apps/admin/src/lib/api.ts apps/admin/src/lib/openapiClient.ts apps/admin/src/lib/api.test.ts apps/admin/src/lib/generated/api.d.ts`

## Status

- **Priority**: P2 (060 Phase 6)
- **Effort**: M
- **Risk**: MEDIUM (wire requests must stay identical; admin UI)
- **Depends on**: 171 (client + middleware + getArticle pilot)
- **Category**: admin client / typed contracts
- **Planned at**: commit `64f99891`, 2026-10-19

## Why this matters

Plan 171 proved the pattern on one endpoint. The remaining **read-only GETs**
still build URLs and generic types by hand. Migrating them removes string
paths and drift from the generated contract. Mutations stay on `apiFetch`
(their 409/422 bodies are already handled and their payloads need more care);
this plan touches GETs only.

## Current state

- `apps/admin/src/lib/openapiClient.ts` — typed client + middleware (token at
  request time, full error taxonomy). `getArticle` already migrated.
- `apps/admin/src/lib/api.ts` — remaining GETs (all with `apiFetch`):
  `listArticles(status, pageSize, cursor)`, `getSourceHealth()`,
  `getAnalytics()`, `getConfig()`, `getCollectStatus(runId?)`,
  `getPublishStatus(runId?)`, `listSources()`, `getPrompts()`, `getContent()`,
  `getQualityRecent(limit=20)`, `getImageQueue()`.
- Tests in `api.test.ts` cover the error taxonomy and several calls; the
  middleware tests are already in place from 171.
- Generated `paths` include these routes (verify each before migrating).

## Scope

**In scope**: `apps/admin/src/lib/api.ts` (GET functions only),
`apps/admin/src/lib/api.test.ts` (or a new focused test), `plans/060/todo.md`
(note the batch; keep the checkbox open until mutations are done too).

**Out of scope**: mutations (`POST/PUT/DELETE`), `apiFetch` semantics,
`generated/api.d.ts`/`openapi.json` (never hand-edit), backend/serving code.

## Rules

- Keep every exported signature and return type unchanged.
- The **wire request must be byte-identical** for the same arguments: same
  path, same query names/encoding (`page_size`, `run_id`, `limit`, `status`,
  `cursor`), same method. If a generated type/param name differs from the
  current wire, STOP and report (do not silently rename).
- Use the existing middleware; no new error mapping. If a generated response
  type is looser than the handwritten one, use a narrow documented cast like
  `getArticle` (never `any`).
- Migrate only endpoints whose generated path exists and whose response shape
  is compatible; list any skipped endpoint and why.

## Steps

1. For each GET, confirm the generated path and query names; note mismatches.
2. Migrate in this order (simplest first): `getSourceHealth`, `getAnalytics`,
   `getConfig`, `listSources`, `getPrompts`, `getContent`, `getImageQueue`,
   `getQualityRecent`, `getCollectStatus`, `getPublishStatus`, `listArticles`.
3. Add/extend tests: for each migrated GET, assert the URL/query the client
   sends (mock fetch) and the parsed return; keep the existing error tests.
   A parameterized test table is fine.
4. `plans/060/todo.md`: update the Phase 6 note with the batch; keep the
   checkbox open (mutations remain).
5. Gates: `make admin-test`, `make admin-lint`, `make admin-build`,
   `make admin-contracts-check`, `make lint`, `make type` (committed),
   `make test`, `make test-boundaries`, `make inventory-refresh && make inventory-check`,
   `make plans-ledger-check`.

## Done criteria

- [ ] All listed GETs use the typed client; signatures/returns unchanged
- [ ] Wire paths and query names identical to the previous client (tests)
- [ ] Mutations and their tests untouched
- [ ] Admin/backend gates green; Phase 6 note updated
- [ ] Ledger row 172 updated by the reviewer

## STOP conditions

- A generated path/query name differs from the current wire → report; do not
  change the API request shape.
- A generated response type is materially wrong (not just looser) → report and
  leave that endpoint on `apiFetch`.
- The migration forces changes outside `api.ts`/tests → report.
- Any backend change is needed → STOP.
