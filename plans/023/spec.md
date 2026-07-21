# Plan 023 working notes: durable, contract-valid, abuse-resistant report pipeline

Authoritative spec: `plans/023-connect-and-harden-report-pipeline.md`. All
code changes live in the sibling Astro repo
(`/home/carlos/VS_Code_Projects/products/noticiencias/noticiencias`), not
this backend repo — this plan is frontend/Worker work indexed here for
workspace coordination only.

## Status: PARTIAL (code/tests complete; production enablement is an operator action)

All 5 steps are implemented and tested. The one remaining item —
"Production endpoint is enabled only after its R2/abuse-control
prerequisites exist" — is a genuine STOP condition: provisioning a real
Cloudflare R2 bucket/KV namespace requires account access I don't have.
`src/config.yaml`'s `form.endpoint` stays `''` until an operator does that
(see `docs/report-pipeline-setup.md`, written this session, for the exact
steps).

## What changed (frontend repo, all committed there)

**Step 1 — contract**: `src/utils/reportPayload.ts` (new) maps the form's
camelCase field names to the Worker's snake_case contract. A new test,
`tests/report-form-contract.test.ts`, imports both `buildReportPayload` and
the Worker's real `validateReportPayload` (cross-package relative import —
works because `validate.ts` has no Workers-runtime dependency) and asserts
every UI problem type round-trips to a Worker-valid payload.

**Step 2 — honest form behavior**: `ReportForm.astro`'s script:
- Fixed the double-init bug: dropped the redundant
  `readyState==='complete'`/`DOMContentLoaded` branch — `astro:page-load`
  alone fires on every page load including the first (Astro's documented
  ClientRouter behavior, confirmed `<ClientRouter fallback="swap" />` is
  present in `Layout.astro`), so there's now exactly one init path instead
  of two that could both fire in the same page load.
- No endpoint configured → submit button disabled with a visible
  "no disponible" message from the start, not a silent 800ms fake-success
  simulation. Defense-in-depth check repeated in the submit handler itself.
- Real endpoint branch now distinguishes 429 ("demasiados intentos"), 503
  ("no disponible temporalmente"), 422 (shows the Worker's validation
  error), and treats any other non-2xx or a response missing `id` as a
  generic error — success UI only renders after a genuine 2xx with a
  report id in the body.

**Step 3 — request bounds** (`workers/src/utils/validate.ts`, rewritten):
- Fixed the hostname check from suffix-match (`endsWith('noticiencias.com')`
  — matched `evilnoticiencias.com`) to a real dot-boundary check.
- Rejects unexpected top-level fields.
- Fixed a real gap: a non-string `description` (e.g. an injected object)
  previously skipped validation silently (the length check was gated
  behind `typeof === 'string'` with no else-branch error) — now every
  optional field goes through one `validateOptionalString` helper that
  always type-checks first.
- **Also changed the enum itself**: the six UI categories
  (`content_factual` etc., already snake_case) replaced the Worker's
  original disconnected six values (`error_factual` etc.) — a deliberate
  contract-design call, not just a mapping shim, since nothing was live
  yet and the UI's categories are the ones editors actually see. Added
  three new optional fields end to end (`content_snippet`, `tech_browser`,
  `tech_os`) that the form collected but the old contract had no slot for.
- Body-size bound (`workers/src/handlers/report.ts`): 20KB cap enforced via
  both `Content-Length` and a bounded stream read (so an absent/understated
  header can't bypass it) before `JSON.parse` ever runs.

**Step 4 — durable acceptance** (`report.ts`): tracks `storedDurably`/
`emailSent` independently; returns 201 only if at least one is true, 503
otherwise (previously always 201 regardless). Neither the reporter's
email nor description is logged (verified by a dedicated test).

**Step 5 — abuse controls**:
- Rate limiting: KV-backed fixed-window counter
  (`workers/src/utils/rateLimit.ts`), 5 req/min/IP — deliberately KV, not a
  paid Durable-Object/WAF rate-limiting product, per the plan's own STOP
  condition against unapproved paid infrastructure. New optional
  `RATE_LIMIT_KV` binding (commented in `wrangler.toml`, same
  provision-then-bind pattern as the existing R2/STATUS_KV bindings).
- Idempotency: same KV, keyed by a SHA-256 hash of the raw body, 10-minute
  window — a retried identical submission gets the original report's id
  back instead of creating a duplicate R2 object/email.
- Deploy gates: `.github/workflows/deploy-worker.yml`'s test job now also
  runs `tsc --noEmit` and `vitest run --coverage` (thresholds: 80% lines/
  functions/statements, 70% branches — passing at 84/81/84/80% as of this
  session).

## Tests added/changed (all passing)

- `workers/tests/report.test.ts` — rewritten for the new enum/fields; 15
  cases including the dot-boundary fix, unexpected-field rejection, and
  non-string-description rejection.
- `workers/tests/report.handler.test.ts` (new) — 12 cases exercising the
  real `handleReport()` with mocked `Env` bindings (plain Node
  Request/Response/crypto globals, no `@cloudflare/vitest-pool-workers`
  needed since the handler only uses standard Web APIs): 422/400/413×2/
  503/201×4/rate-limit/idempotency/no-PII-logged.
- `tests/report-form-contract.test.ts` (new, root Vitest) — Step 1's
  contract test.
- `tests/playwright/report-form.test.ts` — expanded from 4 thin/tolerant
  tests to 11: the original ones plus honest-no-endpoint,
  success-with-id, 422/429/503/network-error, and a genuine
  double-navigation-no-duplicate-request test. Required adding a
  test-only `window.__NOTICIENCIAS_TEST_REPORT_ENDPOINT__` override
  (set via `page.addInitScript`) since the static build bakes
  `config.yaml`'s endpoint into the page at build time — there's no other
  way to exercise the "endpoint configured" code paths against the real
  build without either baking a fake endpoint into production config or
  adding this narrow, clearly-documented test seam.

**Found and fixed along the way**: my first idempotency implementation
wrote a placeholder random UUID as the KV "reservation" value instead of
the eventual real report id, so a retry got back a different id than the
original — caught by the handler test itself, fixed by generating the
report id before touching KV. Also found the existing Playwright tests
were using `/reportar-problema/` (trailing slash) against a site
configured `trailingSlash: 'never'` — silently "passing" only because the
old tests tolerate a missing form via `test.skip`. Fixed in the new test
file; **did not fix** the same latent bug in the pre-existing, unrelated
`tests/playwright/accessibility.test.ts` (blog/buscar/newsletter/article
pages) — out of scope for this plan, flagging here so it isn't lost.

## Verification run this session

- `workers/`: `npm test` (27 passed), `npx tsc --noEmit` (clean),
  `npm run test:coverage` (84.07% stmts / 80.43% branch / 81.25% funcs /
  83.97% lines — all above threshold).
- Root: `npx vitest run tests/ --exclude tests/playwright` (137 passed,
  including the new contract test), `npx astro check` (1 pre-existing
  unrelated error in `Metadata.astro`, already uncommitted before this
  session — not touched).
- `npx playwright test tests/playwright/report-form.test.ts` against a
  fresh local build/preview (11/11 passed) and
  `tests/playwright/accessibility.test.ts` (1 passed, 5 pre-existing
  failures — all trailing-slash 404s unrelated to this plan, confirmed via
  `git log` that file predates this session).
- `npx eslint`/`npx prettier --check` on every touched file — clean.

## Remaining work (operator action, see docs/report-pipeline-setup.md)

1. `npx wrangler r2 bucket create noticiencias-reports`, uncomment the R2
   binding in `workers/wrangler.toml`.
2. `npx wrangler kv namespace create RATE_LIMIT_KV`, uncomment + fill in
   the id.
3. (Optional) email provider secrets (`EMAIL_API_KEY`/`EMAIL_FROM`/
   `EMAIL_TO`) if a second notification channel is wanted.
4. Only then: set `src/config.yaml`'s `form.endpoint` to
   `https://noticiencias.com/api/report` and deploy both the Worker and
   the frontend.
