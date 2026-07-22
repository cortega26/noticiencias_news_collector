# Plan 031 TODO

## Pre-work
- [x] Read the full plan file `plans/031-enforce-representative-frontend-tests.md`.
- [x] Ran the plan's own prescribed drift check
      (`git -C ../noticiencias diff --stat 0cdca74..HEAD -- ...`) —
      showed only plan 023's own already-accounted-for report-contract
      growth, no unexpected drift.
- [x] Confirmed both STOP-adjacent deps satisfied: 023's Worker/report
      *contract* is done and tested (production enablement, separately
      blocked on operator Cloudflare provisioning, is out of scope for
      031); 030 is archived/DONE.
- [x] Verified Playwright feasibility empirically: cached chromium
      binaries already present, a real headless run against
      `npm run preview`'s local server executed and produced a genuine
      pass/fail (found a real bug in the process — see spec.md).
- [x] Verified Cloudflare Workers Vitest-pool feasibility: package
      resolves on the registry (`npm view
      @cloudflare/vitest-pool-workers version` → 0.18.7); not yet
      installed (that's Step 3's own work).

## Step 1: Honest unit coverage — DONE
- [x] Added the missing `resolve.alias['~']` to `vitest.config.ts`
      (tsconfig had it, Vitest never did — see spec.md for the masked
      `trim()` coverage gap this caused).
- [x] Wrote 11 new test files covering previously-0%-covered production
      modules in `src/utils/`, `src/navigation.ts`,
      `src/content.config.ts` (the sealed schema's `superRefine`
      branches), and `src/integration/utils/{loadConfig,configBuilder}.ts`.
- [x] Deleted confirmed-dead `src/utils/search-url.ts` (zero importers);
      fixed the one pre-existing test that read its file content to
      point at the real, live pure module (`src/utils/search.ts`)
      instead.
- [x] Fixed a genuine type/runtime mismatch in
      `configBuilder.ts`'s `Config.apps.blog` (was full `BlogConfig`,
      runtime always accepted partial — narrowed the type to
      `Partial<BlogConfig>`).
- [x] Set `coverage.exclude` to genuinely justified entries only
      (`**/*.d.ts`, `src/types/config.ts` — verified type-only,
      `workers/**` — owned by its own config).
- [x] Set per-file `coverage.thresholds` (`perFile: true` + one entry per
      existing file at its measured value) rather than a global-only
      floor, because a global floor did not trip on a deliberately
      injected uncovered branch in a small file — verified empirically,
      documented in spec.md.
- [x] Verify: `npm run test:coverage` clean; injected-branch regression
      check reproducibly fails the gate on the specific file, restored
      byte-for-byte after; `npm run test:audit` 35/35 files, 200/200
      tests (was 24/137); `npm run build` unchanged (166 pages);
      `npx astro check` — one pre-existing, unrelated error only;
      `prettier`/`eslint` clean on every touched file.

## Step 2: Deterministic, fail-closed local Playwright tests — mostly DONE
- [x] Caught myself hitting exactly the bug this step exists to fix: ran
      `report-form.test.ts` without `PLAYWRIGHT_BASE_URL` and 6 tests
      failed against **live production** (the old config's silent
      default) instead of the local build. Fixed at the root —
      `playwright.config.ts` now defaults to `http://localhost:4321`
      unconditionally and runs `webServer` in CI too; no live-site
      fallback remains anywhere in this config.
- [x] `report-form.test.ts`: removed the 404-acceptance and all 7
      conditional `test.skip` blocks (form is always present in a real
      build).
- [x] `article-rendering.test.ts`: removed the "no article" skip and the
      vacuous `>= 0` JSON-LD count check; verified empirically there are
      4 JSON-LD blocks per article (not 1), validates all of them.
- [x] `navigation.test.ts`: removed a vacuous "redirects to correct
      domain" test that no longer tested anything real (confirmed via
      git history — an `if (localhost)` branch had been added to make it
      pass trivially everywhere).
- [x] `accessibility.test.ts`: fixed its `getFirstArticleUrl` helper,
      which was appending a trailing slash to article URLs and 404ing;
      removed its "no article" skip too.
- [x] Found and surfaced (did not silently resolve) a genuine
      trailing-slash mismatch between the local build (`trailingSlash:
      false`) and observed production behavior
      (`/buscar/` = 200, `/buscar` = 301) — asked the operator directly
      via `AskUserQuestion` rather than guessing. They chose to hold this
      specific question for further investigation and confirmed
      `astro preview` as the local server. The 5 affected tests across 3
      files are marked `test.fixme(...)` with an inline explanation, not
      silently skipped or force-fixed either direction.
      `src/navigation.ts`'s own hardcoded `/buscar/` href was
      deliberately left untouched — out of this plan's scope, and
      plausibly correct for production as observed.
- [x] Verify: `npx playwright test --project=chromium` → 23 passed, 7
      explicit `fixme`, 0 unexplained failures; `npm run test:audit`
      still 35/35, 200/200 (Step 1 untouched); `npx astro check` same
      single pre-existing unrelated error; `prettier` clean.

## Step 3: Worker fetch-boundary tests — STOPPED (plan's own STOP condition)
- [x] Checked (not assumed): every published `@cloudflare/vitest-pool-workers`
      version back to 0.16.11 requires `vitest ^4.1.0`.
- [x] Checked: `workers/package.json` pins `vitest: "4.0.18"` exactly,
      deliberately synced to the main repo's pin one day before this
      session (`git show 8f435bb`, by the operator, for Node 24
      alignment) — not incidental, not something to quietly bump.
- [x] This is the plan's own named STOP condition ("Stop if the
      supported Cloudflare pool conflicts with the locked test runner;
      resolve in plan 030 before continuing") — 030 is archived/DONE, so
      there's no "continue in 030" path; documented as a genuine stop,
      not pushed through.
- [x] Read `workers/tests/report.handler.test.ts` (208 lines, from plan
      023) so whoever unblocks this knows it already covers a chunk of
      the fetch-boundary surface and should extend it, not duplicate it.
- [ ] Not done: pool installation, config migration, the 8 boundary test
      cases, enabling `typecheck.enabled` — all blocked on the version
      conflict above.

## Step 4: content-guard.yml gates — DONE for coverage + Playwright
- [x] Replaced the `test:audit` CI step with `test:coverage` (same tests
      + Step 1's thresholds now actually gate PRs).
- [x] Added a cached Playwright-browser-install step and a browser-suite
      step with `CI=true PLAYWRIGHT_BASE_URL=http://localhost:4321`
      explicitly set (never relying on the config default alone).
- [x] Added `actions/upload-artifact` on failure for
      `playwright-report/`/`test-results/`, SHA verified against the
      real `v4.6.2` tag via `gh api` (a first guess at the hash was
      wrong — checked rather than shipped).
- [x] Confirmed no report-contents/secret leakage risk: every
      report-form test mocks `page.route`, nothing hits a real endpoint.
- [ ] Not added: a Worker-test CI gate — blocked by Step 3.
- [x] Verify: YAML validates (`python3 -c "import yaml; yaml.safe_load"`,
      `prettier --check`); simulated the new CI steps locally end-to-end
      (`test:dist`, `test:coverage`, `CI=true PLAYWRIGHT_BASE_URL=...
      npx playwright test`) before trusting them to GitHub Actions.
      `actionlint` unavailable in this sandbox — noted honestly, not
      silently skipped.

## Plan 031 final status: PARTIAL
- [x] Step 1: DONE. Step 2: DONE except 5 tests `fixme` pending the
      operator's trailing-slash investigation. Step 3: STOPPED on its
      own named condition. Step 4: DONE for coverage+Playwright, blocked
      on the Worker gate by Step 3.
- [ ] Update `plans/README.md`, root `spec.md`/`todo.md` to reflect this
      final PARTIAL status.
