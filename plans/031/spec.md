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

## Steps 2-4: not yet done

Feasibility for both is already confirmed above (Playwright runs
headless here with cached chromium binaries; the Cloudflare Vitest pool
package resolves and installs). Resuming with Step 2 next.
