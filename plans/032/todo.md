# Plan 032 — Running to-do

Status: ` ` = pending · `~` = in progress · `x` = done · `!` = blocked

## Pre-flight

- [x] Read `plans/032-migrate-frontend-dependencies.md` in full
- [x] Verify plan 031's fail-closed local browser suite is available (STOP gate)
- [x] Confirm `../noticiencias` exists and is a sibling repo
- [x] Drift check: `git -C ../noticiencias log 0cdca74..HEAD -- package.json astro.config.mjs tailwind.config.js src/layouts src/components/template/common src/utils/images.ts src/styles tests`
- [x] Stash unrelated uncommitted frontend changes (sitemap filter, robots.txt, SEO robots)
- [x] Record baseline: `npm ls` (invalid Astrolib peers), `npm audit` (7 vulns incl 4H/1C), build (166 pages), e2e (23 pass / 7 skip), metadata snapshots captured for home/article/buscar/notfound
- [x] Confirm harness fails as expected at baseline (deps, audit, no-astrolib all red)

## Step 1 — Compatible security fixes (no major)

- [x] Create branch `advisor/032-supported-frontend-graph` in frontend repo
- [x] Run `npm audit fix` (non-`--force`) in `../noticiencias`
- [x] Verify tar + svgo vulns gone; sharp NOT bumped yet (critical tar gone, svgo high gone; 2 high remain = Astro XSS + sharp libvips, deferred to Step 4)
- [x] Run V1 (deps — Astrolib invalids remain, expected) + V5 (build — 166 pages stable) + V6 (validate — test:dist + test:audit pass; validate:content fails on pre-existing freeze-template baseline condition, documented in spec) + V7 (e2e — 23 passed)
- [x] Commit: `build: land compatible production security patches` (4260f17)

## Step 2 — Remove `@astrolib/seo` and `@astrolib/analytics`

- [x] Rewrite `src/components/template/common/Metadata.astro` to render all tags directly (escaped attrs, safe JSON-LD) — via new `buildHead.ts` helper
- [x] Replace `src/components/template/common/Analytics.astro` with minimal prod-only inline script
- [x] Replace `import type { OpenGraph } from '@astrolib/seo'` in `src/utils/images.ts` with local narrow type (`seo.ts`)
- [x] Remove `@astrolib/seo` + `@astrolib/analytics` from `package.json`; `npm install`
- [x] Run V3 (no-astrolib ✓) + V4 (metadata-snapshot byte-match on all 4 routes ✓) + V6 (test:dist + test:audit pass) + V7 (e2e 23/23 ✓)
- [x] Commit: `build: remove unsupported @astrolib wrappers` (00f0265) — also folds in operator's pending baseline tweaks (sitemap filter, robots.txt, max-image-preview:large)

## Step 3 — Move Tailwind to a supported integration

- [x] Audit `tailwind.config.js` plugins, `@apply`, custom tokens, dark mode, fontsource imports — `@tailwindcss/typography` plugin, custom `intersect` variant, 14 `@apply` usages, CSS-variable-driven tokens, dark mode (class strategy)
- [x] Migrate `@astrojs/tailwind` → `@tailwindcss/vite`; update `astro.config.mjs` (vite.plugins)
- [x] Rewrite `tailwind.css` to Tailwind 4 CSS-first config (`@import`, `@theme`, `@plugin`, `@custom-variant`, `@utility`); delete `tailwind.config.mjs`
- [x] Add 375px (Pixel 5) + 1280px (Desktop Chrome) projects to `playwright.config.ts`
- [x] Run V1 (deps clean ✓ — npm ls exits 0) + V5 (build 166 pages ✓) + V8 (visual — e2e 46 passed / 14 skipped at both viewports ✓) + V6 (vitest 220 ✓) + V7 (e2e ✓)
- [x] Commit: `build: move Tailwind to @tailwindcss/vite` (cdb922f)

## Step 4 — Upgrade Astro + official integrations to v7

- [x] `rg -n "src/fetch" ../noticiencias` → not present (reserved in v7, no rename needed)
- [x] Sätteri Markdown default: no remark/rehype plugins wired into astro.config.mjs (frontmatter.ts plugins are dead code, never imported) — Sätteri is the default with no migration
- [x] Bump `astro` ^6.4.6→^7.1.3, `@astrojs/mdx` ^5→^7.0.3, `@astrojs/rss` ^4.0.18→^4.0.19, `@astrojs/sitemap` ^3.6.1→^3.7.3
- [x] Land `sharp@0.35.3` here (libvips CVE fixes) — pulls GHSA-f88m-g3jw-g9cj
- [x] `astro check` clean — 0 errors, 0 warnings (fixed top-level `return` in BasicScripts.astro inline script guard; Rust compiler rejected it, Go silently accepted)
- [x] `compressHTML: 'jsx'` default — only diff is charset meta case (UTF-8→utf-8) on 404; no whitespace regressions in e2e
- [x] Run V1 (deps clean ✓) + V4 (metadata byte-identical ✓) + V5 (166 pages ✓) + V6 (vitest 220 ✓) + V7 (e2e 46 ✓) + V8 (visual ✓) + V2 (audit zero high/critical ✓)
- [x] Commit: `build: migrate to Astro 7` (aa32be6)

## Step 5 — Close audit and compatibility gates

- [x] Remove resolved audit allowlist exceptions — no allowlists existed; the production audit is now clean (zero high/critical) after Steps 1+4
- [x] Add CI peer-validity check (`npm ls --omit=dev` exits 0) to `.github/workflows/content-guard.yml`
- [x] Document supported Node/Astro/Tailwind matrix — `docs/supported-dependency-matrix.md`
- [x] Fix Playwright CI step to use new project names (mobile-375 + desktop-1280, was chromium)
- [x] Add `buildHead.ts` + `seo.ts` to freeze-template allowlist
- [x] Fix ESLint error in Analytics.astro (set:html for inline script body)
- [x] Run V2 (audit ✓ zero high/critical) + V9 (ci-peer-check ✓) + V6 (lint ✓, test:dist ✓, test:audit ✓ — validate:content fails on pre-existing freeze-template baseline condition) + V7 (e2e 46 ✓)
- [x] Commit: `ci: enforce peer-validity and close audit gates` (2b98e30)

## Close-out

- [ ] Update `plans/README.md` row for plan 032 to DONE
- [ ] Run full `tests/harness.sh all` green
- [ ] Note any intentional metadata/visual diffs in spec.md
- [ ] ~iteration 20: fresh sub-agent review of spec.md vs implementation
