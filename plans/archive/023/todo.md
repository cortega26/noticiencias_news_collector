# Plan 023 TODO

## Step 1: Define one wire contract and mapping
- [x] `src/utils/reportPayload.ts` — camelCase UI → snake_case Worker mapping
- [x] Contract test feeding builder output into the real `validateReportPayload`

## Step 2: Fail honestly in the form
- [x] Fix double-init (single `astro:page-load` listener, no redundant readyState/DOMContentLoaded branch)
- [x] No endpoint → visibly disabled, never fake success
- [x] Success only after real 2xx + report id in body
- [x] Playwright: missing endpoint, success, 422, 429, 503, network error, double-navigation-no-duplicate-request

## Step 3: Enforce strict request bounds
- [x] Body byte-limit (20KB) via Content-Length + bounded stream read
- [x] Reject unexpected top-level fields
- [x] Fix non-string-description silent-pass gap
- [x] Hostname dot-boundary fix (was suffix-match, allowed lookalike domains)
- [x] Bound evidence_url/email/all optional-field lengths
- [x] Redesigned the problem_type enum to match the UI's real categories + added content_snippet/tech_browser/tech_os fields

## Step 4: Require durable acceptance
- [x] Track R2/email outcomes independently; 201 only if ≥1 succeeded, 503 otherwise
- [x] Verified no PII (email/description) in logs (dedicated test)
- [x] R2 bucket `noticiencias-reports` provisioned + binding uncommented (2026-08-11)

## Step 5: Add abuse controls and deploy gates
- [x] KV-backed rate limiting (5/min/IP) — free-tier, not paid infra (STOP condition)
- [x] KV-backed idempotency (10-min window, keyed by payload hash)
- [x] Deploy gate: added typecheck + coverage (80% thresholds) to deploy-worker.yml
- [x] `RATE_LIMIT_KV` namespace provisioned + binding fixed (id had landed in the unused STATUS_KV block)

## Final gate
- [x] `src/config.yaml` `form.endpoint` = `https://noticiencias.com/api/report` (2026-08-11)
      — done only after the R2 sink was verified live (201 + durable object + idempotent retry).

## Verification (all run this session, all green)
- [x] `workers/`: `npm test` (27), `tsc --noEmit`, `npm run test:coverage` (thresholds met)
- [x] Root: `npx vitest run tests/ --exclude tests/playwright` (137)
- [x] `npx astro check` (only a pre-existing, unrelated, already-uncommitted error)
- [x] `npx playwright test tests/playwright/report-form.test.ts` (11/11) against a fresh build/preview
- [x] eslint/prettier clean on every touched file

## Noted, not fixed (out of scope for this plan)
- `tests/playwright/accessibility.test.ts` has the same pre-existing
  trailing-slash 404 bug (blog/buscar/newsletter/reportar-problema/article
  pages) that I fixed locally in the new report-form test file. Predates
  this session (confirmed via `git log`) — not part of plan 023's scope.
