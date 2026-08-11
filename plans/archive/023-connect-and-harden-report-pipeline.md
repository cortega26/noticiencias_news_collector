# Plan 023: Make reader reports durable, contract-valid, and abuse-resistant

> **Executor instructions**: This plan is frontend/Worker work stored in the backend plan index for workspace coordination. Update plan 023 only after the frontend branch passes all gates.
>
> **Drift check (run first)**: in `../noticiencias`, run `git diff --stat 0cdca74..HEAD -- src/config.yaml src/components/template/widgets/ReportForm.astro workers/src workers/tests workers/wrangler.toml workers/package.json .github/workflows/deploy-worker.yml tests/playwright/report-form.test.ts`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 018 for the later Refinery direction only; core report delivery has no code dependency
- **Category**: bug/security/tests
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The public form currently waits 800 ms and shows success when no endpoint is configured. If enabled, its camelCase fields and problem values fail the Worker's snake_case contract. The Worker can return 201 when neither R2 nor email succeeds, accepts weakly typed/oversized values, and exposes a cost-bearing anonymous route without application-level abuse controls.

## Current state

- `src/config.yaml:70-73` configures an empty endpoint.
- `ReportForm.astro:231-240` can initialize twice; `:347-357` attaches listeners without an initialized marker.
- `ReportForm.astro:386-417` sends raw `FormData` keys and treats missing endpoint as success.
- `workers/src/utils/validate.ts:11-26` expects snake_case and a different enum; `:54-59` uses suffix-only hostname matching.
- `workers/src/handlers/report.ts:42-76` treats both sinks as optional and always acknowledges.
- `workers/tests/report.test.ts` tests only the validation function.
- `workers/wrangler.toml:25-28` leaves the production R2 binding commented.
- Worker deployment at `.github/workflows/deploy-worker.yml:18-39` is gated only by those validator tests.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Worker unit/integration | `cd ../noticiencias/workers && npm test` | all pass |
| Worker typecheck | `cd ../noticiencias/workers && npx tsc --noEmit` | exit 0 |
| Frontend unit | `cd ../noticiencias && npm run test:audit` | all pass |
| Browser | `cd ../noticiencias && PLAYWRIGHT_BASE_URL=http://localhost:4321 npm run test:e2e -- tests/playwright/report-form.test.ts` | all pass against local preview |

## Scope

**In scope**: the listed form/config/Worker files, Worker runtime tests, focused Playwright tests, deployment gate, and an operator setup section for R2/rate limiting.

**Out of scope**: building the Refinery inbox (plan 047), public report-status pages, collecting additional personal data, or choosing a new email vendor unless the existing integration cannot work.

## Git workflow

- Frontend branch: `advisor/023-durable-reader-reports`
- Commit example: `fix(reports): deliver validated reports durably`.

## Steps

### Step 1: Define one wire contract and mapping

Create a typed, browser-only payload builder near the form that maps UI values to the Worker's snake_case fields and canonical enum. Keep Worker validation authoritative. Add a contract test that feeds the actual builder output to `validateReportPayload`.

**Verify**: every UI problem type produces a valid Worker payload; unknown types and unexpected fields fail.

### Step 2: Fail honestly in the form

Configure the same-origin `/api/report` endpoint only when production Worker routing is ready. When no endpoint exists, disable submission and explain unavailability; never simulate success. Initialize each form exactly once across `astro:page-load` transitions and show success only after a 2xx response with a report ID.

**Verify**: Playwright covers missing endpoint, success, 422, 429, 503, network error, and two ClientRouter navigations without duplicate requests.

### Step 3: Enforce strict request bounds

Before parsing, reject bodies over a documented byte limit using `Content-Length` when present and a bounded read otherwise. Require exact field types and maximum lengths, reject arrays/objects, and accept article hosts only when hostname equals `noticiencias.com` or ends with `.noticiencias.com` at a dot boundary. Bound evidence URLs and email length.

**Verify**: Worker tests cover oversized bodies, lookalike domains, non-string fields, Unicode-length edges, and valid subdomains.

### Step 4: Require durable acceptance

Track sink outcomes. Return 201 only after at least one configured durable sink succeeds; return 503 if no sink is configured or all fail. Provision and bind the production R2 bucket before enabling the frontend endpoint. Do not log report bodies or email addresses.

**Verify**: Worker-runtime tests mock R2/email and assert R2 success, email-only success, one-sink failure, all-sinks failure, and missing bindings.

### Step 5: Add abuse controls and deploy gates

Add request-rate protection using the platform-supported mechanism and document its deployment command/dashboard setting. If Turnstile is chosen, validate tokens server-side and do not make the secret optional in production. Add idempotency for repeated client retries. Gate deploy on Worker runtime tests, typecheck, and coverage thresholds.

**Verify**: repeated identical submissions do not create duplicate durable records; rate-limit tests return 429; deploy workflow runs all new gates.

## Test plan

- Browser-to-Worker contract tests for every UI type, optional field, and unknown field/type.
- Worker runtime tests for request bounds, hostname boundaries, sink combinations, idempotency, rate limits, and secret-free logs.
- Playwright cases for unavailable, success, validation, throttling, service failure, network failure, and repeated Astro navigation.
- Worker typecheck/coverage and frontend full validation before enabling the production route.

## Done criteria

- [ ] Form and Worker share a contract verified by executable tests.
- [ ] Missing endpoint or failed delivery never displays success.
- [ ] At least one durable sink is required for 201.
- [ ] Body, fields, URLs, automation, and retries are bounded.
- [ ] Worker runtime tests, typecheck, coverage, and Playwright pass.
- [ ] Production endpoint is enabled only after its R2/abuse-control prerequisites exist.

## STOP conditions

- Stop if the production R2 bucket or equivalent durable sink has not been provisioned; do not enable the form endpoint.
- Stop if adding rate limiting requires unapproved paid infrastructure; report the platform options and keep the endpoint disabled.
- Stop if any test fixture contains a real reporter email, API key, or account identifier.

## Maintenance notes

Treat report records as potentially sensitive editorial data. Retention, access, and future Refinery ingestion must preserve least privilege and avoid exposing reporter identity to public feeds.
