# Plan 157: The admin client must surface why a capability is unavailable

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat efe20fcb..HEAD -- apps/admin/src/lib/api.ts apps/admin/src/lib/api.test.ts apps/admin/src/pages/content.astro apps/admin/src/lib/types.ts docs/ci.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 151 (DONE, merged `cbc7f964` — it introduced the 503 contract)
- **Category**: dx / bug (operator-facing)
- **Planned at**: commit `efe20fcb`, 2026-10-19

## Why this matters

Plan 151 made the three published-content routes answer **503 with
`error_code=published_content_unavailable`** and a `detail` that names the missing
requirement, instead of a 500. But the Astro admin client does not read it:
`apps/admin/src/lib/api.ts` turns any non-2xx into a generic
`NetworkError("Cannot reach the serving API … (HTTP 503)")`. So the operator who
opens the Content page against the hosted serving API sees "network error" and
will debug the network — not "this deployment has no checkout/git", which is the
truth and is actionable.

The backend now has a machine-readable error contract; the client should carry it
through to the UI. This is the missing half of plan 151.

## Current state

- `apps/admin/src/lib/api.ts` — `apiFetch` (and the error type it throws): the
  non-2xx path builds a generic `NetworkError` with the status code and does not
  parse the JSON body. Read the exact class/fields before changing it; the 503 is
  raised by `getPublishedContent` / `deletePublishedContent` /
  `bulkResetPublishedContent` (the functions behind the Content page).
- `apps/admin/src/pages/content.astro` — the page that calls those functions and
  renders its error state.
- `apps/admin/src/lib/api.test.ts` — the vitest suite for `api.ts` (existing
  fetch-mocking pattern to follow).
- The backend contract (from plan 151, `news_collector/serving/api.py`):
  `{"detail": "Published content is unavailable in this deployment. This route
  requires the local admin stack: … (missing here: …).", "error_code":
  "published_content_unavailable"}` with status 503.
- `apps/admin/package.json` — `test` (vitest), `lint` (prettier + eslint). Node 24.

## Commands you will need

| Purpose            | Command                                              | Provenance | Expected on success        |
|--------------------|------------------------------------------------------|------------|----------------------------|
| Admin install      | `make admin-install`                                 | declared   | exit 0                     |
| Admin tests        | `make admin-test`                                    | declared   | all pass                   |
| Admin lint         | `make admin-lint`                                    | declared   | exit 0                     |
| Admin build        | `make admin-build`                                   | declared   | exit 0                     |
| OpenAPI check      | `make admin-contracts-check`                         | declared   | exit 0 (no route change)   |
| Backend baseline   | `make lint && make test`                             | declared   | exit 0                     |
| Ledger             | `make plans-ledger-check`                            | declared   | `validate_plans_ledger: OK`|

Provenance: all `declared`.

## Scope

**In scope**:

- `apps/admin/src/lib/api.ts` — parse an error body when present; carry
  `status`, `error_code` and `detail` on the thrown error (keep `NetworkError`
  for genuine transport failures)
- `apps/admin/src/lib/api.test.ts` — tests for: a 503 with the capability body →
  the error exposes `errorCode === "published_content_unavailable"` and the
  detail; a 503 with a non-JSON body → still a clean error (no crash); a 500 with
  a JSON body → same parsing path
- `apps/admin/src/pages/content.astro` — render the detail (one callout) when
  `errorCode === "published_content_unavailable"`, else keep the current generic
  message
- `apps/admin/src/lib/types.ts` — only if the error shape needs a type

**Out of scope** (do NOT touch):

- The backend (the contract is correct and tested).
- Any other page's error handling (do not refactor the client broadly).
- `apps/admin/openapi.json` / generated types (no route or schema change).
- `apps/admin/package.json` (plan 145 owns the dependency work).

## Git workflow

- Branch: `advisor/157-admin-503-error-code`
- Conventional commits, e.g. `fix(admin): surface the published-content 503 reason (plan 157)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

`make admin-install` (if `apps/admin/node_modules` is absent), `make admin-test`,
`make admin-lint`, `make admin-build`. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Carry the error contract through `apiFetch`

1. Read `apiFetch`'s current error path. On a non-2xx response, attempt to parse
   the body as JSON (`content-type` may be absent in tests — guard it): if it has
   `error_code` and/or `detail`, include them on the thrown error (new optional
   fields or a subclass; keep the existing message for logs).
2. Genuine network failures (fetch rejects) keep the existing `NetworkError`.
3. Do not change any success-path behaviour or the request payloads.

**Verify**: `make admin-test` → all pass after adding the tests.

### Step 2: Tests (red first where practical)

Add vitest cases in `apps/admin/src/lib/api.test.ts`:

- 503 + `{detail, error_code}` → the thrown error exposes `errorCode` and
  `detail`, and still has the status.
- 503 + HTML/plain body (not JSON) → a clean error, no parse crash.
- 500 + JSON body → the same parsing path.
- Existing success-path tests unchanged.

**Verify**: `make admin-test` → green, including the new cases.

### Step 3: Show it on the Content page

4. In `content.astro`'s error handling: if `errorCode ===
   "published_content_unavailable"`, render the `detail` in a short callout
   ("Published content requires the local admin stack…"); otherwise keep the
   current generic message. Use the page's existing styling/classes (read it
   first; do not introduce a new component).

**Verify**: `make admin-lint && make admin-build` → green.

### Step 4: Prove the contract end to end (optional if cheap)

5. If a local serving API is running with the capability missing (e.g. the
   container from plan 151's smoke on port 8125 with `ADMIN_API_KEY=test`), point
   the admin at it and confirm the callout text appears. Otherwise rely on the
   vitest cases and say so.

**Verify**: the recorded evidence (or the explicit note that only the unit level
was exercised).

## Test plan

As in Step 2. No backend change; `make admin-contracts-check` must stay green
(no schema change).

**Verify**: `make admin-test && make admin-lint && make admin-build` → green.

## Done criteria

All must hold:

- [ ] `make admin-test`, `make admin-lint`, `make admin-build` exit 0
- [ ] `make admin-contracts-check` exits 0 (no generated-type drift)
- [ ] A 503 capability response yields an error carrying `errorCode` and `detail` (test)
- [ ] `content.astro` renders the detail for that code and keeps the generic path otherwise
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 157 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- `apiFetch` already parses the body on errors (the premise is gone) → report.
- The page's error state is shared with other views in a way that would make a
  capability-specific callout misleading → report and implement only the client
  part.
- `make admin-test` fails on the unmodified tree → broken baseline; STOP.

## Maintenance notes

- The pattern to keep: **structured backend errors are carried, not swallowed**.
  Any future 4xx/5xx with an `error_code` gets the same treatment without a new
  abstraction.
- Reviewer should scrutinise: no JSON parse on an empty body crashes the client,
  and the generic message is still used when there is no structured error.
- **Deferred:** a shared error-presentation helper for all admin pages. Unblocked
  by a second page needing the same callout.
