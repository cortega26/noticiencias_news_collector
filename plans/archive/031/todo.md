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
- [x] Trailing-slash investigation CONCLUDED 2026-08-11: production
      serves the slash form as canonical (200 on `/buscar/`, `/blog/`,
      `/reportar-problema/`, `/newsletter/`, `/categorias/*/`,
      `/temas/*/`; 301 from no-slash), the site's own nav links are
      authored in slash form, but `config.yaml` `trailingSlash: false`
      made the local build 404 on every slash route and emit no-slash
      canonicals — stale config. Fixed: `trailingSlash: true`,
      `navigation.ts` `reportar-problema` link normalized to slash form,
      all 5 `test.fixme(...)` route assertions un-fixme'd with the
      resolution noted.
- [x] Verify (post-fix): `npx playwright test --project=mobile-375
      --project=desktop-1280` → 39 passed, 0 failures (was 23 passed +
      7 fixme); `npm run test:audit` 43/43 files, 284/284 tests;
      `prettier` clean.

## Step 3: Worker fetch-boundary tests — DONE (2026-08-11)
- [x] Historical STOP resolved on its own: Dependabot commit `8be5e11`
      (2026-08-11) bumped `workers/` vitest 4.0.18 -> 4.1.10 (same as the
      main repo), which satisfies the pool's `^4.1.0` peer — the
      toolchain-lock decision was made upstream, no manual bump needed.
- [x] `@cloudflare/vitest-pool-workers@0.21.1` installed (latest; the
      0.18.x line dragged in vulnerable wrangler/miniflare — 0.21.1 uses
      wrangler 4.121.0 / miniflare 5.x, `npm audit` clean). Replaced the
      old `defineWorkersConfig` import with the new `cloudflareTest()`
      plugin API (0.21.x dropped the `./config` subpath).
- [x] `workers/vitest.config.ts` migrated to the pool with real miniflare
      bindings (`REPORT_BUCKET` R2 + `RATE_LIMIT_KV`); `typecheck.enabled`
      flipped on; coverage provider v8 -> istanbul (the pool explicitly
      rejects v8: "node:inspector is not functional in the Workers
      runtime" — documented Cloudflare known issue).
- [x] New `workers/tests/fetch-boundary.test.ts` (12 tests) exercises the
      real exported `fetch` boundary inside workerd: routing (201/404,
      method dispatch), CORS preflight (204 + headers), malformed JSON
      (400), schema rejection (422), oversized body (413), rate limiting
      (429 after 5), idempotency (same id on retry), no secret/email
      leakage, /api/health. Each test uses a unique client IP because
      pool storage is shared per test file and rate limiting keys on
      CF-Connecting-IP (found empirically: the first run's 6th request
      was 429).
- [x] `tsconfig.json` + `worker-configuration.d.ts` (generated by
      `wrangler types`) added to the include set; `cloudflare:test` env
      cast to the Worker's own `Env` type (generated Cloudflare.Env
      marks bindings optional).
- [x] Full suite: 39 tests green (was 27), coverage 91.71% lines (was
      84.07%), typecheck clean, `npm audit` 0 vulnerabilities.

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
- [x] Worker-test CI gate added: `⚙️ Worker suite (fetch-boundary +
      coverage, workerd runtime)` step in `content-guard.yml`'s build job
      (runs `npm run test:coverage` in `workers/`); the existing
      `deploy-worker.yml` gate (typecheck + coverage) now also exercises
      the pool tests on `workers/**` changes.
- [x] Verify: YAML validates (`python3 -c "import yaml; yaml.safe_load"`,
      `prettier --check`); simulated the new CI steps locally end-to-end
      (`test:dist`, `test:coverage`, `CI=true PLAYWRIGHT_BASE_URL=...
      npx playwright test`) before trusting them to GitHub Actions.
      `actionlint` unavailable in this sandbox — noted honestly, not
      silently skipped.

## Plan 031 final status: DONE
- [x] Step 1: DONE. Step 2: DONE including the trailing-slash
      investigation (stale config fixed, 5 fixme tests green). Step 3:
      DONE (pool installed, boundary tests in workerd, typecheck +
      coverage green). Step 4: DONE — coverage, Playwright, and Worker
      gates all wired.
- [x] Update `plans/README.md`, root `spec.md`/`todo.md` to reflect this
      status.
