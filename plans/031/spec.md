# Spec: Plan 031 — Enforce representative frontend, browser, and Worker tests

## Goals

Per `plans/031-enforce-representative-frontend-tests.md` (the
authoritative plan file — this document only tracks this plan's own
execution):

- Step 1: an honest unit-coverage denominator with no-regression
  thresholds.
- Step 2: deterministic, fail-closed local-build Playwright tests.
- Step 3: Worker fetch-boundary tests in a Cloudflare-compatible Vitest
  pool.
- Step 4: require all of the above as gates in `content-guard.yml`.

## Startability check (2026-07-22)

Both STOP-adjacent dependencies are satisfied for the frontend-repo work
this plan actually needs:

- **023** ("Connect and harden the report pipeline"): PARTIAL, but the
  part 031 depends on — the Worker/report *contract* — is done and
  tested (`workers/src/handlers/report.ts`, the honest disabled-by-default
  form, request bounds, durable-sink tracking, rate limiting). Only
  *production enablement* (Cloudflare R2/KV/API-token provisioning) is
  separately blocked on the operator's own account access — that is out
  of scope for 031, which tests behavior against a local build, not the
  live deployment.
- **030** ("Lock developer toolchains"): archived/DONE.

Drift check run first, as the plan instructs:
`git -C ../noticiencias diff --stat 0cdca74..HEAD -- vitest.config.ts playwright.config.ts tests package.json package-lock.json workers .github/workflows/content-guard.yml`
— showed only 023's own already-accounted-for report-contract work
(report-form tests, Worker handler/validate/rateLimit growth). No
unexpected drift.

## Harness feasibility check (2026-07-22, run before writing anything)

Per the plan's own instruction ("run the test suite locally... before
enabling required CI gates"), verified empirically rather than assumed:

- **Playwright**: chromium binaries were already cached
  (`~/.cache/ms-playwright/chromium-1228` etc.) from prior use in this
  sandbox. A live headless run
  (`PLAYWRIGHT_BASE_URL=http://localhost:4321 npx playwright test
  tests/playwright/search.test.ts`) actually launched the browser, drove
  the existing `webServer` (`npm run preview`), and produced a real
  pass/fail result (3 passed, 1 genuine failure — see finding below).
  **Verifiable in this environment.**
- **Cloudflare Workers Vitest pool**: `workers/vitest.config.ts`
  currently runs plain Node Vitest, not
  `@cloudflare/vitest-pool-workers` — confirmed by reading
  `workers/package.json` (no such dependency) and
  `workers/tests/report.test.ts` (tests only the pure `validate.ts`
  helper, never the exported `fetch` handler). `npm view
  @cloudflare/vitest-pool-workers version` resolved successfully
  (registry reachable, package installable). **Feasibility confirmed for
  Step 3**; the pool itself is adopted as part of Step 3's work.

## A genuine finding surfaced while checking Playwright feasibility

`tests/playwright/navigation.test.ts`'s existing `search page loads` test
asserts `page.goto('/buscar/')` returns 200. Against the local
`astro preview` build this actually 404s — `/buscar` (no trailing slash)
returns 200, `/buscar/` (with slash) returns 404. The test currently only
"passes" against the live `https://noticiencias.com` (where a CDN/host
layer evidently normalizes the trailing slash) — exactly the class of bug
this plan's Step 2 exists to catch: a test that looks green but never
actually exercises the local build it's supposed to gate. Left as-is for
Step 1 (Step 2 rewrites this file); recorded here so it isn't lost.

## Step 1: honest unit coverage — done and verified (2026-07-22)

### What changed

- **`vitest.config.ts`**: added `resolve.alias['~'] -> src/` (previously
  absent — see finding below), broadened `coverage.exclude` to all
  `**/*.d.ts` plus `src/types/config.ts` (type-only interfaces, zero
  runtime code — same class as a `.d.ts` file) and `workers/**` (owned
  and thresholded independently by `workers/vitest.config.ts`, avoiding
  double-counting). Added per-file `coverage.thresholds` (see below).
- **New unit tests** for previously-0%-covered production modules,
  chosen because CLAUDE.md's own law is "utilities must stay pure; no
  DOM in `src/utils/`" — these are exactly that layer:
  `tests/date.test.ts`, `tests/directories.test.ts`,
  `tests/frontmatter.test.ts`, `tests/safe-fs.test.ts` (path-traversal
  guard — security-relevant), `tests/json-ld.test.ts` (XSS-safe
  serialization — security-relevant, includes a real
  `String.fromCharCode(0x2028/0x2029)` separator-character test, not a
  fake one), `tests/utils-trim.test.ts`, `tests/normalize-image.test.ts`,
  `tests/navigation.test.ts`, `tests/content-config-schema.test.ts`
  (the `superRefine` cross-field validation on the sealed
  `src/content.config.ts` contract — `image_alt` requirement,
  `featured_rank` requirement, `STRICT_EDITORIAL` schema_version>=2
  gating), `tests/load-config.test.ts`, `tests/config-builder.test.ts`
  (the SITE/I18N/APP_BLOG default-merge contract every other test in the
  suite already has to mock).
- **Deleted** `src/utils/search-url.ts` — confirmed zero importers
  anywhere in the repo (grepped broadly, including `.astro`). It was a
  stray duplicate re-export; the real, used, DOM-touching module is
  `src/utils/browser/search-url.ts`. One pre-existing test
  (`tests/quick-wins-regression.test.ts`) read this dead file's *content*
  via `fs.readFileSync` (not an import) to assert "the pure search logic
  has no DOM globals" — fixed to point at `src/utils/search.ts`, the
  actual currently-live pure module, restoring the test's real intent
  instead of leaving a dependency on dead code alive just to keep an
  already-slightly-broken assertion green.
- **Small type-correctness fix**: `configBuilder.ts`'s `Config.apps.blog`
  was typed as full, all-required `BlogConfig`, but the function's own
  runtime behavior (`lodash.merge` over defaults) has always accepted
  partial overrides — a genuine pre-existing type/runtime mismatch,
  narrowed to `Partial<BlogConfig>` so the type matches actual behavior.

### A real, load-bearing finding: the `~` alias was never wired into Vitest

`tsconfig.json` declares `~/* -> src/*` for the TypeScript compiler/IDE,
but `vitest.config.ts` had no matching `resolve.alias`. Any source file
importing via `~/...` was simply unresolvable under plain Vitest.
Confirmed empirically: importing `src/utils/date.ts` alone failed with
`Cannot find package 'astrowind:config'` until mocked (expected), but
importing `src/navigation.ts` (which reaches `permalinks.ts`, which
imports `trim` via `~/utils/utils`) failed with `Cannot find module
'~/utils/utils'` even *with* the virtual-module mock in place.

The existing workaround, found in `tests/component/permalink.test.ts`,
was `vi.mock('~/utils/utils', () => ({ trim: (str, ch) => { if (!ch)
return str.trim(); ... } }))` — a hand-copied reimplementation of `trim`,
not the real one. That reimplementation is *not equivalent*: the real
`src/utils/utils.ts::trim` does not default to whitespace-trimming when
no character argument is given (confirmed by a genuine test failure
while writing `tests/utils-trim.test.ts` — `trim('  hello  ')` returns
`'  hello  '` unchanged, not `'hello'`), but the mock's copy silently
does. This means `src/utils/utils.ts::trim` had **zero real test
coverage** before this pass, masked by a test double that quietly
diverged from production behavior. Fixed at the root: added the missing
`resolve.alias` so `~/` resolves for real everywhere, eliminating the
need for that class of workaround going forward (existing tests using
the old mock pattern still pass — the mock isn't wrong to *have*, it's
just no longer the only path, and its own file wasn't touched).

### Coverage denominator decisions

Included, thresholds set at currently-measured value (no artificial
floor-raising attempted this pass — accepted, documented gaps, kept
*in* the denominator so they stay visible in every report rather than
hidden via exclude):

- `src/utils/images-optimization.ts`, `src/utils/images.ts` — both
  deeply coupled to Astro's real `astro:assets`/`import.meta.glob`
  pipeline; mocking `getImage` enough to test meaningfully would test the
  mock, not our logic. Real follow-up, not attempted here.
- `src/pages/llms.txt.ts`, `src/pages/llms-full.txt.ts` — real page
  endpoints, currently untested; lower priority than the utility layer
  for this pass.
- `src/integration/index.ts` — Astro integration hook wiring (needs
  `AstroIntegration` hook-argument scaffolding); indirectly proven by
  `npm run build` succeeding, but not unit-tested directly.

Excluded, with justification (not "convenience"):

- `**/*.d.ts` and `src/types/config.ts` — verified: 100% `interface`
  declarations, zero runtime code to instrument. Same class of thing a
  `.d.ts` file is, just not named as one.
- `workers/**` — has its own independent coverage thresholds in
  `workers/vitest.config.ts` (Step 3's concern); listing it here too
  would double-count and confuse "which config governs this file."

### Thresholds: per-file, not global-only — and why

An aggregate global threshold is too coarse for the plan's own Step 1
Verify line: "a copied uncovered branch added to a covered fixture causes
the threshold check to fail." Tested this directly — injecting an
unreachable branch into the already-100%-covered `src/utils/json-ld.ts`
did **not** trip a loose global floor (one small file's branch is diluted
across dozens of files), but did trip immediately once each file got its
own `coverage.thresholds['src/utils/json-ld.ts']` entry set at its
current value. `coverage.thresholds` supports exactly this shape
(confirmed by reading `node_modules/vitest/dist/chunks/reporters.d.*.d.ts`
— `{ [glob: string]: Pick<Thresholds, ...> } & Thresholds`). Final
config: `perFile: true` with a lenient `0` global default (so a
not-yet-classified new file doesn't block CI before someone adds its own
entry), plus one explicit entry per existing file at its measured
value (floored to the nearest whole percent, e.g. 97.67% → 97).

### Verify (all confirmed empirically, not asserted)

- `npm run test:coverage` passes cleanly against the new
  include/exclude/thresholds.
- Regression check: reproducibly injected an unreachable branch into
  `src/utils/json-ld.ts`, re-ran `npx vitest run --coverage
  tests/json-ld.test.ts`, confirmed the threshold gate fails
  specifically on `src/utils/json-ld.ts` (75%/50%/100%/75% vs. its
  100%/100%/100%/100% floor), then restored the file byte-for-byte
  (`diff` confirmed identical) before any commit.
- Full regression suite: `npm run test:audit` → 35 files / 200 tests
  passed (was 24 files / 137 tests before this plan; net +11 files,
  +63 tests, zero pre-existing tests broken).
- `npm run build` → 166 pages, unchanged.
- `npx astro check` → the one remaining error
  (`src/components/template/common/Metadata.astro:29`, an
  `AstroSeoProps`/`robotsProps.maxImagePreview` type mismatch) is
  pre-existing and unrelated — present in the repo's uncommitted state
  before this session touched anything in this plan; not introduced by
  this work.
- `npx prettier --check` / `eslint .` clean on every file this plan
  touched.

## Step 2: deterministic, fail-closed local Playwright tests — mostly done (2026-07-22)

### The bug this step exists to catch, caught in the act

While fixing this step, I ran `tests/playwright/report-form.test.ts`
without `PLAYWRIGHT_BASE_URL` set and got 6 failures — the "no endpoint
configured" test saw a *populated* endpoint (contradicting this repo's
own `config.yaml`), and every mocked-response test's assertions came back
empty. Root cause: `playwright.config.ts`'s old default
(`BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'https://noticiencias.com'`)
meant that without the env var, `page.goto('/reportar-problema')`
silently hit **live production**, not the local build — even though the
`webServer` block dutifully started `npm run preview` in the background
for readiness-checking purposes. The webServer running does not make it
the navigation target; only `baseURL` does. I had fallen into exactly the
bug this plan exists to fix, mid-way through fixing it. Confirmed by
re-running the identical test with `PLAYWRIGHT_BASE_URL=http://localhost:4321`
explicitly — all 11 tests passed.

**Fix**: `playwright.config.ts` now defaults `BASE_URL` to
`http://localhost:4321` unconditionally (no live-site fallback at all),
and `webServer` now runs in CI too (previously `undefined` in CI, meaning
a CI run — had one ever been wired up — would have silently exercised
live production with no local server at all). Live-site checking stays
exactly where the plan says it belongs: the pre-existing, separate
`npm run test:deploy` (`scripts/post-deploy-check.js`), untouched.

### Test-file changes

- **`tests/playwright/report-form.test.ts`**: removed the `toBeLessThan(500)`
  404-acceptance on page load (now requires a real 200) and all 7
  `if (form.count() === 0) test.skip(...)` conditional skips — the form is
  always present in a real build, so these were dead branches masking
  the fact the tests had likely never actually run against anything real
  before (see finding above).
- **`tests/playwright/article-rendering.test.ts`**: rewritten. Removed
  the "no article found, skip" fallback (a local build's search index is
  never empty) and the vacuous `expect(count).toBeGreaterThanOrEqual(0)`
  on JSON-LD blocks. New version asserts a hero image has real alt text,
  and validates *every* JSON-LD block on the page (there are 4 in
  practice, not the 1 I initially assumed — checked empirically before
  asserting an exact count).
- **`tests/playwright/navigation.test.ts`**: removed the
  `'noticiencias.com redirects to correct domain'` test entirely — git
  history shows it once did a real `expect(url).toContain('noticiencias.com')`
  check, but a later commit added an `if (baseURL.includes('localhost'))`
  branch that made it pass trivially against any host, for any reason,
  with no actual redirect behavior anywhere in this codebase to test
  (confirmed: no `_redirects` file, no redirect config in
  `astro.config.mjs`). A vacuous test, removed rather than patched again.
- **`tests/playwright/accessibility.test.ts`**: fixed its own
  `getFirstArticleUrl` helper, which explicitly appended a trailing
  slash to article URLs ("for local preview consistency" — backwards;
  see the trailing-slash finding below) causing the article a11y check
  to 404; now uses the URL from `search.json` as-is, matching
  `article-rendering.test.ts`'s already-correct pattern. Removed its
  "no article found" skip for the same reason as above.

### An unresolved, genuinely load-bearing finding: trailing-slash mismatch

`/blog/`, `/buscar/`, `/reportar-problema/`, `/newsletter/` all 404
locally under `astro preview` (`trailingSlash: false` in
`src/config.yaml`), while the no-slash form (`/blog`, `/buscar`, etc.)
returns 200. **Production does the opposite**: confirmed by curling
`https://noticiencias.com/buscar/` (200) and `https://noticiencias.com/buscar`
(301, redirecting to the slash form). This is either (a) `config.yaml`'s
`trailingSlash: false` is stale relative to how the site is actually
hosted (Cloudflare Pages likely applies its own default trailing-slash
normalization independent of the Astro build config), or (b) production
is doing something unexpected that should itself be treated as a bug.

**Asked the operator directly rather than guessing** (this is a real
infra/deployment question no amount of reading this repo's code can
answer) — they asked to hold this specific question for further
investigation rather than pick one now, and confirmed `astro preview`
(not `wrangler pages dev ./dist`) as the local server for this plan.
Every route-load assertion that depends on this (5 tests across 3 files)
is marked `test.fixme(...)` with a comment explaining exactly why and
pointing back to this finding — not silently skipped, not guessed at.
`src/navigation.ts`'s own hardcoded `href: '/buscar/'` was **left
untouched**: given production's observed behavior, that hardcoded
trailing slash is actually the form that works directly (200) in
production today, so "fixing" it to match the local build's `never`
config would plausibly make it *worse* in production (add a redirect
hop) to fix a local-only symptom — exactly the kind of change plan 031's
own scope excludes ("changing article/product behavior").

### Verify

- `npx playwright test --project=chromium`: 23 passed, 7 `fixme`
  (explicitly reasoned, not silent), 0 unexplained failures/skips.
- `npm run test:audit`: still 35/35 files, 200/200 tests (Step 1
  untouched).
- `npx astro check`: same single pre-existing, unrelated error only.
- `prettier --check` clean on every touched file.

## Step 3: Worker fetch-boundary tests via the Cloudflare Vitest pool — STOPPED (2026-07-22)

The plan's own STOP condition fires here: "Stop if the supported
Cloudflare pool conflicts with the locked test runner; resolve in plan
030 before continuing." 030 is archived/DONE, so there is no "continue
in 030" path available — this is a genuine, not a soft, stop.

**The conflict, checked rather than assumed**: `npm view
@cloudflare/vitest-pool-workers peerDependencies` for every published
version back to 0.16.11 (the oldest checked) requires `vitest ^4.1.0`.
`workers/package.json` pins `vitest: "4.0.18"` **exactly** — and that
pin is not incidental. `git show 8f435bb` (2026-07-21, the day before
this session, by the operator themselves) is titled "build: align
vitest, coverage-v8, and @types/node with Node 24 runtime" and explicitly
"Sync[s] workers vitest to same pinned version" as the main repo, for a
stated Node-24-compatibility reason. Adopting the Cloudflare pool would
require bumping `workers/`'s vitest from 4.0.18 to 4.1.x+ — undoing a
deliberate, one-day-old, reasoned toolchain decision, exactly the kind of
call this plan's own STOP condition reserves for a dedicated toolchain
plan (030's lineage), not a test-authoring plan.

**Not attempted**: installing the pool, migrating
`workers/vitest.config.ts`, writing the 8 fetch-boundary cases (allowed/
blocked origin, OPTIONS, malformed JSON, schema rejection, success, rate
limiting, upstream timeout/error, secret absence), enabling
`typecheck.enabled` (currently `false` in `workers/vitest.config.ts`; the
`typecheck` npm script already exists — `tsc --noEmit` — so that part of
Step 3's ask is a one-line config flip, not new tooling, once the vitest
version conflict is resolved).

**What already exists and would need reusing, not duplicating, once
unblocked**: `workers/tests/report.handler.test.ts` (208 lines, added by
plan 023) — read in full; it already covers a substantial share of the
fetch-boundary surface (success, validation/schema rejection, rate
limiting) via direct calls to the exported handler with a mocked `Env`,
just not yet inside an actual `workerd` runtime. Migrating to the
Cloudflare pool should extend/re-point these fixtures, not replace them.

**To unblock**: either (a) the operator upgrades `workers/`'s vitest to
4.1.x+ as its own deliberate toolchain decision (verify it doesn't
reintroduce whatever the Node 24 alignment commit was fixing), or (b) a
future Cloudflare pool release adds support for vitest 4.0.x (checked as
of 2026-07-22 — none does). Either way, that call belongs with whoever
owns the toolchain-lock decision, not folded quietly into this plan.

## Step 4: partially done — gates that don't depend on Step 3 (2026-07-22)

Coverage (Step 1) and Playwright (Step 2) gates are now wired into
`content-guard.yml`'s `build` job (PR-only, matching the existing job's
own `if: github.event_name == 'pull_request'`):

- Replaced the `✅ Audit Suite` (`npm run test:audit`) step with
  `✅ Unit Coverage` (`npm run test:coverage`) — same test files, plus
  Step 1's per-file thresholds now actually gate the PR instead of just
  being locally runnable.
- Added a cached Playwright-browser install step (keyed on
  `package-lock.json`, matching the existing Astro-image-cache pattern
  in the same job) and a `🎭 Browser Suite` step running
  `npx playwright test --project=chromium` with `CI=true` and
  `PLAYWRIGHT_BASE_URL=http://localhost:4321` explicitly set — never
  relying on the config's own default, belt-and-suspenders against the
  exact silent-live-site bug found in Step 2.
- Added `actions/upload-artifact` (pinned by SHA, verified against the
  real `v4.6.2` tag via `gh api` rather than guessed — a first attempt at
  guessing the hash was wrong) on failure, uploading
  `playwright-report/` and `test-results/`. Confirmed this cannot leak
  report contents or secrets: every report-form test mocks `page.route`
  for `**/api/report`, so no real submission ever reaches a real
  endpoint in these tests.
- **Not added**: any Worker gate — blocked by Step 3's STOP above. No
  `content-guard.yml` job currently runs Worker tests at all (that gap
  pre-dates this plan and remains open).

### Verify

- `npm run test:dist` (166 files), `npm run test:coverage` (thresholds
  pass), and `CI=true PLAYWRIGHT_BASE_URL=http://localhost:4321 npx
  playwright test --project=chromium` (23 passed, 7 fixme, sequential
  `workers: 1` — matches how the real CI job will run it) all run
  cleanly locally, simulating the new CI steps end-to-end before
  trusting them to GitHub Actions.
- YAML validated with `python3 -c "import yaml; yaml.safe_load(...)"`
  and `prettier --check`. `actionlint` was not available in this
  sandbox (no Go toolchain/binary) — flagging honestly rather than
  claiming a check that didn't run.

## Overall plan 031 status: PARTIAL

- Step 1: DONE, verified.
- Step 2: DONE for everything not gated on the trailing-slash question;
  5 tests `fixme` pending the operator's own further investigation.
- Step 3: STOPPED on its own named condition (Cloudflare pool requires
  vitest ^4.1.0; `workers/` deliberately pins 4.0.18 as of yesterday).
- Step 4: DONE for the coverage + Playwright gates; Worker gate blocked
  by Step 3.

Real, load-bearing findings from doing this work rather than assuming:
the Vitest `~` alias was never wired (masked a real coverage gap), the
Playwright config silently defaulted to production, a genuine local/
production trailing-slash mismatch (unresolved, operator's call), and a
genuine, dated toolchain-version conflict blocking Step 3. None of these
were guessed at or silently patched around.
