# Plan 031: Enforce representative frontend, browser, and Worker tests

> **Executor instructions**: Build gates around observable behavior, not inflated percentages. Run the test suite locally against a production build before enabling required CI gates. Update plan 031 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- vitest.config.ts playwright.config.ts tests package.json package-lock.json workers .github/workflows/content-guard.yml`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/023-connect-and-harden-report-pipeline.md, plans/030-lock-developer-toolchains.md
- **Category**: tests
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The frontend's unit coverage measures only importable TypeScript utilities, production Playwright defaults to the live website, and several browser tests accept missing features or impossible assertions. Worker tests exercise only a pure validator, not the deployed fetch boundary. Required checks should fail when a local production build or Worker behavior regresses.

## Current state

- `../noticiencias/vitest.config.ts` includes only `tests/**/*.test.ts`; coverage includes `src/**/*.ts` with no thresholds.
- `../noticiencias/playwright.config.ts` defaults to `https://noticiencias.com` and starts no local production server in CI.
- `../noticiencias/tests/playwright/report-form.test.ts` accepts HTTP 404 and skips when the form is absent.
- `../noticiencias/tests/playwright/article-rendering.test.ts` asserts that structured-data count is `>= 0`, which cannot fail.
- `../noticiencias/.github/workflows/content-guard.yml` builds and audits output but does not run browser or coverage gates.
- `../noticiencias/workers/vitest.config.ts` disables type checking, and `workers/tests/report.test.ts` tests only validation helpers.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit coverage | `npm --prefix ../noticiencias run test:coverage` | exit 0 and thresholds met for declared source set |
| Local browser | `CI=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:4321 npm --prefix ../noticiencias run test:e2e` | all tests run against the local production build and pass |
| Worker | `npm --prefix ../noticiencias/workers test` | fetch-boundary and validator tests pass in Workers-compatible runtime |
| Full gate | `npm --prefix ../noticiencias run lint && npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist && npm --prefix ../noticiencias run test:audit` | exit 0 |

## Scope

**In scope**: frontend Vitest/Playwright configuration and tests, Worker test/type configuration and fetch-boundary tests, package scripts, and `content-guard.yml`.

**Out of scope**: changing article/product behavior, using production as the PR test target, setting coverage thresholds for `.astro` files without valid instrumentation, or report contract implementation already covered by plan 023.

## Git workflow

- Branch: `advisor/031-representative-frontend-tests` in the frontend repository.
- Commit example: `test: gate local site and worker behavior`.

## Steps

### Step 1: Define honest unit coverage

Restrict the denominator to importable production modules that Vitest actually instruments. Record current line/branch/function values, set no-regression thresholds at or just below measured values, and add explicit tests for any high-risk module below the chosen floor. Do not count fixtures, generated files, config, or tests as production.

**Verify**: `npm --prefix ../noticiencias run test:coverage` → thresholds pass; a copied uncovered branch added to a covered fixture causes the threshold check to fail.

### Step 2: Make browser tests deterministic and fail closed

Configure CI to build and serve `dist/` locally and require `PLAYWRIGHT_BASE_URL`. Keep live-environment smoke tests as a separate, explicit post-deploy command. Remove 404 acceptance, conditional skips for required UI, and vacuous assertions. Assert one valid JSON-LD block on article pages, canonical metadata, critical images, navigation, search, and the report interaction from plan 023.

**Verify**: the local Playwright command runs every required test with zero skipped tests; renaming a required selector in a disposable copy produces a failure.

### Step 3: Exercise the Worker's deployed boundary

Adopt Cloudflare's supported Vitest pool/runtime for the Worker version in the lockfile. Add a `typecheck` script and tests that call the exported Worker fetch handler with mocked environment bindings. Cover allowed/blocked origin, OPTIONS, malformed JSON, schema rejection, success, rate limiting, upstream timeout/error, and secret absence. Reuse plan 023's contract fixtures.

**Verify**: Worker typecheck and tests exit 0; removing an environment binding in a fixture yields the expected fail-closed response.

### Step 4: Require the gates in pull requests

Add unit coverage, local Playwright, Worker typecheck/tests, and artifact upload on failure to `content-guard.yml`. Cache only lockfile-keyed dependencies. Ensure browser failures include traces/screenshots without leaking report contents or secrets.

**Verify**: workflow syntax validates and a CI-equivalent local run passes from a clean install.

## Test plan

- Unit: real source denominator and a tested no-regression threshold.
- Browser: home, article metadata/rendering, search, page transition, report form; no required-test skips.
- Worker: request/response integration for every branch listed in step 3.
- CI: local server readiness, artifact-on-failure, and production smoke separation.

## Done criteria

- [ ] Pull requests test a local production build, never the live site by default.
- [ ] Required browser assertions can fail and do not skip absent features.
- [ ] Worker fetch behavior and types are tested in a compatible runtime.
- [ ] Coverage has an explicit, honest source set and no-regression thresholds.
- [ ] Full frontend validation passes.

## STOP conditions

- Stop if plan 023 has not defined the Worker/report contract needed by integration fixtures.
- Stop if Astro source maps make `.astro` coverage unreliable; exclude it explicitly and keep behavior under Playwright.
- Stop if the supported Cloudflare pool conflicts with the locked test runner; resolve in plan 030 before continuing.

## Maintenance notes

Any new public route needs at least metadata/render smoke coverage. Any new Worker branch needs a fetch-boundary test, not just a helper unit test.
