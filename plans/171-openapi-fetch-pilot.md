# Plan 171: Adopt `openapi-fetch` for one admin endpoint (Phase 6 pilot)

> **Executor instructions**: Follow the plan, run every verification, stop on
> STOP conditions. Commit in the worktree per the git section.
>
> **Drift check**: `git diff --stat d18fde38..HEAD -- apps/admin/package.json apps/admin/src/lib/api.ts apps/admin/src/lib/openapiClient.ts apps/admin/src/lib/api.test.ts apps/admin/src/lib/generated/api.d.ts`

## Status

- **Priority**: P2 (060 Phase 6, first pending item)
- **Effort**: S-M
- **Risk**: MEDIUM (auth/error semantics; admin UI)
- **Depends on**: 080 Phase 2 (generated OpenAPI/TS), 168 (ConflictError body use)
- **Category**: admin client / typed contracts
- **Planned at**: commit `d18fde38`, 2026-10-19

## Why this matters

`openapi-typescript` is pinned (7.13.0) and its generated types are consumed,
but the runtime client is a hand-written `apiFetch` with string paths and manual
generics. 060 Phase 6 calls for `openapi-fetch` adoption endpoint by endpoint.
A pilot proves the pattern (compile-time paths/params/responses) without a
big-bang rewrite, while keeping the auth and error taxonomy the UI depends on.

## Current state

- `apps/admin/src/lib/api.ts` — `apiFetch<T>(path, init)` + error classes:
  `AuthError` (401), `NotFoundError` (404), `ValidationError` (422),
  `ConflictError<Body>` (409, carries the parsed body), `ApiError` (structured
  4xx/5xx with `detail`/`error_code`), `NetworkError` (fetch rejects or
  unstructured 502/503/504).
- Token: `getToken()` from sessionStorage (`refinery_admin_token`), sent as
  `Authorization: Bearer`; `clearToken()` on 401 paths.
- `apps/admin/src/lib/generated/api.d.ts` — `paths` from the committed
  `openapi.json`; `/v1/admin/articles/{article_id}` exists.
- `getArticle(id)` returns `AdminArticleDetail` and is used by `article.astro`
  and `triage.astro`; tests in `api.test.ts`.
- `openapi-fetch` is **not** a dependency; latest stable is `0.17.0` (pin exactly
  and record it in the commit/PR).

## Scope

**In scope**: `apps/admin/package.json` (+lock), new
`apps/admin/src/lib/openapiClient.ts`, `apps/admin/src/lib/api.ts` (only
`getArticle` migrated), `apps/admin/src/lib/api.test.ts` (+ a focused test file
if cleaner), `plans/060/todo.md` (note the pilot; keep the item unchecked because
the migration is endpoint-by-endpoint).

**Out of scope**: migrating other endpoints, changing `apiFetch` semantics,
the generated artifacts (do not hand-edit `generated/api.d.ts`), backend code,
the frontend repo.

## Design

- `openapiClient.ts`:
  - `import createClient, { type Middleware } from 'openapi-fetch'` and
    `type { paths } from './generated/api'` (or the existing type alias).
  - `client = createClient<paths>({ baseUrl: API_BASE })`.
  - A middleware that:
    - adds `Authorization: Bearer <token>` when a token exists (read at request
      time, not module load);
    - on response, mirrors `apiFetch`'s mapping: 401 → `AuthError`, 404 →
      `NotFoundError`, 409 → `ConflictError(body)`, 422 → `ValidationError`,
      structured other non-2xx → `ApiError`, unstructured 502/503/504 → `NetworkError`;
    - reuse a shared `readStructuredError` helper (extract it from `api.ts` or
      export it) so the two clients cannot drift.
- `api.ts` `getArticle`:
  ```ts
  const { data, error, response } = await client.GET('/v1/admin/articles/{article_id}', {
    params: { path: { article_id: id } },
  });
  if (error) throw mapOpenApiError(error, response);
  return data as AdminArticleDetail; // data is already typed; cast only if the generated shape is looser
  ```
  Keep the exported signature and return type unchanged.
- Tests: success + 401/404/409/422 + network + structured/unstructured 5xx,
  asserting the same classes/messages as the `apiFetch` tests.

## Steps

1. Pin `openapi-fetch@0.17.0` (exact, no caret) in `apps/admin/package.json`;
   `npm install` in `apps/admin`.
2. Extract the shared error-body reader if needed; implement the middleware and
   the client.
3. Migrate `getArticle` only; keep every other function on `apiFetch`.
4. Add/adjust tests; run `make admin-test`.
5. `plans/060/todo.md`: update the Phase 6 note to "pilot delivered: getArticle
   on openapi-fetch; remaining endpoints pending", leave the checkbox open.
6. Gates: `make admin-test`, `make admin-lint`, `make admin-build`,
   `make admin-contract-check`, `make lint`, `make type` (committed),
   `make test`, `make test-boundaries`, `make inventory-refresh && make inventory-check`,
   `make plans-ledger-check`.

## Done criteria

- [ ] `openapi-fetch` pinned exactly; lock updated; no other dependency churn
- [ ] `getArticle` uses the typed client; signature/return unchanged
- [ ] Error taxonomy identical (tests for 401/404/409/422/5xx/network)
- [ ] Admin tests/lint/build and backend gates green
- [ ] Phase 6 note updated; ledger row 171 updated by the reviewer

## STOP conditions

- The middleware cannot preserve the exact error classes/messages without
  changing callers → report; do not change the taxonomy.
- The generated path types for the endpoint are missing or incorrect → report
  (regenerate, do not hand-edit).
- A single migrated endpoint forces changes in `article.astro`/`triage.astro` →
  report; keep the pilot internal to `api.ts`.
- Any backend/serving change is needed → STOP.
