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

## Steps 2-4: not yet done
- [ ] Step 2: deterministic, fail-closed local-build Playwright tests
      (remove 404 acceptance, conditional skips, vacuous assertions;
      require `PLAYWRIGHT_BASE_URL` in CI; keep a live-site smoke test
      separate).
- [ ] Step 3: adopt `@cloudflare/vitest-pool-workers`; fetch-boundary
      tests covering allowed/blocked origin, OPTIONS, malformed JSON,
      schema rejection, success, rate limiting, upstream timeout/error,
      secret absence; add a `typecheck` script.
- [ ] Step 4: wire coverage/Playwright/Worker gates into
      `content-guard.yml` as required checks, with artifact-on-failure.
- [ ] Update `plans/README.md`, root `spec.md`/`todo.md` to reflect final
      status once Steps 2-4 land (or document why they stopped, if they
      do).
