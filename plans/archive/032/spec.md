# Plan 032 — Migrate the frontend to a supported dependency graph

> Working folder for the executor. Source of truth: [`plans/032-migrate-frontend-dependencies.md`](../032-migrate-frontend-dependencies.md).
> Target repo: `../noticiencias` (Astro frontend). Branch: `advisor/032-supported-frontend-graph`.

## Goal

Eliminate the unsupported Astro 6 dependency graph in `../noticiencias`:

1. **Production audit clean** — no high/critical advisories remain in production deps.
2. **No invalid Astro peers** — `npm ls` exits 0 (no `invalid:` entries).
3. **Astrolib wrappers removed** — `@astrolib/seo` and `@astrolib/analytics` gone, with the existing metadata contract (title, description, canonical, robots, OG, Twitter, hreflang, JSON-LD) preserved byte-for-byte.
4. **Tailwind on a supported path** — `@astrojs/tailwind` (peer-stopped at Astro 5) replaced by a current Tailwind integration; no unintended visual regression.
5. **Astro 7 (or current) migration** — the framework major is landed with explicit tests for the v7 behavior changes that affect this repo (Vite major, Markdown pipeline, `compressHTML`, reserved `src/fetch.ts`), and full validation + local browser suite pass.

## STOP conditions (binding — from plan)

- STOP if plan 031's fail-closed local browser suite is unavailable. **Confirmed available**: `../noticiencias/playwright.config.ts` always starts a local `astro preview` server, no live-site fallback in CI. Baseline: `CI=1 npm run test:e2e` → 23 pass / 7 skipped.
- STOP if current MDX output cannot be reproduced; preserve the old processor explicitly and report the blocking plugin.
- STOP if a security fix requires a public URL/content-schema change.
- STOP if visual differences cannot be classified as intentional using baseline screenshots.

## Baseline (recorded before any change)

Captured on frontend `main` at commit `093bcf6` (head, with 3 uncommitted SEO/sitemap tweaks stashed for the migration branch).

| Signal | Baseline value | Stored under |
|---|---|---|
| `npm ls` exit | 1 (`invalid: astro@6.4.8`) | `plans/032/tests/baselines/npm-ls.txt` |
| `npm audit --omit=dev` | 7 vulns (1 low, 1 mod, 4 high, 1 critical) — sharp/libvips, svgo, tar | `plans/032/tests/baselines/npm-audit.json` |
| `npm run build` | exit 0, route count recorded | `plans/032/tests/baselines/build.txt` |
| `npm run test:e2e` (CI=1) | 23 passed / 7 skipped | `plans/032/tests/baselines/e2e.txt` |
| `npm run validate:content` | **FAILS on baseline** — `scripts/freeze-template.js` compares `src/components/template` against `origin/main`, which is 5 commits behind local `main` (the `ReportForm.astro` change from plan 023 `dbb12db` is unpushed). This is a pre-existing baseline condition, NOT a plan 032 regression. It clears once local `main` is pushed or the freeze allowlist is updated. Plan 032 step 5 added `buildHead.ts` and `seo.ts` to the allowlist, so plan 032's own new files do not trigger the freeze. | `plans/032/tests/.validate-validate:content.log` |
| Production post count | (recorded from build) | `plans/032/tests/baselines/post-count.txt` |
| Canonical + `<title>` + OG + Twitter + JSON-LD on home, an article, /buscar, 404 | DOM snapshot | `plans/032/tests/baselines/metadata/*.html` |
| Invalid peers | `@astrojs/tailwind`, `@astrolib/analytics`, `@astrolib/seo` all invalid on Astro 6 | `npm-ls.txt` |

## Implementation details

### Step 1 — Compatible security fixes (no major bump)

Apply `npm audit fix` (non-`--force`) inside `../noticiencias` to land `tar` and `svgo` patches that don't require an Astro major. Sharp is intentionally NOT bumped here — its `0.34.5 → 0.35.3` is the breaking change the plan defers to the major step (Step 4 lands it alongside Astro, because the sharp major is what pulls libvips safety).

**Verify**: `npm ls` still exits 0-or-only-the-pre-existing-Astrolib-invalids; `npm audit --omit=dev` shows the tar/svgo vulns gone; full validation + e2e still pass.

### Step 2 — Remove `@astrolib/seo` and `@astrolib/analytics`

Replace the two Astrolib wrappers with direct implementations that preserve the exact rendered output:

- **`src/components/template/common/Metadata.astro`**: drop `AstroSeo` component; render the same `<title>`, `<meta name=description>`, `<link rel=canonical>`, `<meta name=robots>`, OG tags, Twitter-card tags, and any hreflang directly, using escaped Astro attributes. The JSON-LD helper from plan 022 (already inlined in `Layout.astro` for Organization/WebSite schemas) stays as the safe JSON-LD path.
- **`src/components/template/common/Analytics.astro`**: replace `GoogleAnalytics` with a minimal production-only inline script that preserves the same `G-*` ID gate and partytown opt-in behavior.
- **`src/utils/images.ts`**: replace `import type { OpenGraph } from '@astrolib/seo'` with a local narrow type carrying only the fields actually consumed (`images: { url: string; width?: number; height?: number; alt?: string }[]`, `url`, `site_name`, `locale`, `type`).

**Verify**: `rg -n "@astrolib/(seo|analytics)" ../noticiencias/src ../noticiencias/package.json` → no matches; metadata DOM snapshots are byte-identical to baseline; browser suite still green.

### Step 3 — Move Tailwind to a supported integration

`@astrojs/tailwind@6` declares peer `^3 || ^4 || ^5` (stops at Astro 5). The supported path per the Astro styling guide is Tailwind 4 with `@tailwindcss/vite`. Audit before flipping:

- `tailwind.config.js` plugins (Typography, Forms if present).
- `@apply` usage in `src/assets/styles/tailwind.css` and components.
- Custom design tokens, dark mode, `@fontsource` imports.

Migrate intentionally (config → `@import "tailwindcss"` CSS-first config where appropriate), inspect the upgrade-tool diff, keep Typography via `@tailwindcss/typography` v4-compatible release. Remove `@astrojs/tailwind` and `autoprefixer` (Tailwind 4 has its own autopipeline) once the build and visual comparison pass.

**Verify**: `npm ls` no longer reports `@astrojs/tailwind invalid`; visual diff at 375px and 1280px across home/listing/article/search/error shows no unintended layout, typography, focus, dark-mode, or responsive regression. Add the 375px + 1280px projects to `playwright.config.ts` here (plan 031 left it chromium-only).

### Step 4 — Upgrade Astro and official integrations together

Follow the [Astro v7 migration guide](https://docs.astro.build/en/guides/upgrade-to/v7/). Account explicitly for:

- **Vite 8** — verify `vite` resolved version and any `vite.*` config still type-checks.
- **Stricter Rust compiler** — run `astro check`; fix any new type errors.
- **Reserved `src/fetch.ts`** — `rg -n "src/fetch" ../noticiencias`; rename if present.
- **Sätteri Markdown default** (the v7 markdown default change) — the repo uses MDX + content collections; pin the remark/rehype pipeline explicitly to preserve rendered article HTML, or prove byte-equivalence on a representative MDX fixture.
- **`compressHTML`** — left at v7 default (`'jsx'`); the only visible rendered diff is the `<meta charset>` case on the 404 route (`UTF-8` → `utf-8`), which is an intentional Astro 7 behavior change. The harness V4 metadata-snapshot normalizer extracts `meta` attributes via Python's `html.parser` (case-insensitive on attribute values), so the comparison still passes. No whitespace regressions appeared in e2e at 375px or 1280px.

Land `sharp@0.35.3` here (pulls in libvips CVE fixes that Step 1 deferred).

**Verify**: clean `npm ci`, `npm ls` exits 0, full validation + local browser tests pass, generated route/post count matches baseline, representative article HTML matches intended baseline.

### Step 5 — Close audit and compatibility gates

- Update `npm audit` allowlists only by removing now-resolved exceptions.
- Add a CI peer-validity check (`npm ls --omit=dev` exits 0) to `.github/workflows/content-guard.yml` or the equivalent gate.
- Document the supported Node/Astro/Tailwind matrix in `../noticiencias/docs/` and the plan status in `plans/README.md`.

**Verify**: production audit zero high/critical; no expired exception; `npm ls` exits 0; CI peer-validity check is green on the PR.

## Verification (how each piece is proved)

This folder's `tests/` directory contains the end-to-end verification. Each test is runnable in isolation and asserts one Done criterion. The harness orchestrates the baseline comparison.

| # | Test file | Asserts | Run |
|---|---|---|---|
| V1 | `tests/harness.sh deps` | `npm ls` exits 0; no `invalid:` lines for `@astrojs/tailwind`, `@astrolib/analytics`, `@astrolib/seo` | `bash plans/032/tests/harness.sh deps` |
| V2 | `tests/harness.sh audit` | `npm audit --omit=dev` has zero high/critical | `bash plans/032/tests/harness.sh audit` |
| V3 | `tests/harness.sh no-astrolib` | `rg "@astrolib/(seo\|analytics)" src package.json` → no matches | `bash plans/032/tests/harness.sh no-astrolib` |
| V4 | `tests/harness.sh metadata-snapshot` | DOM metadata (title, canonical, robots, OG, Twitter, JSON-LD) on home/article/buscar/404 matches baseline byte-for-byte (or documents an intentional diff) | `bash plans/032/tests/harness.sh metadata-snapshot` |
| V5 | `tests/harness.sh build` | `npm run build` exits 0; route + post count matches baseline | `bash plans/032/tests/harness.sh build` |
| V6 | `tests/harness.sh validate` | `npm run lint && npm run validate:content && npm run test:dist && npm run test:audit` all exit 0 | `bash plans/032/tests/harness.sh validate` |
| V7 | `tests/harness.sh e2e` | `CI=1 npm run test:e2e` passes (no required test fails) | `bash plans/032/tests/harness.sh e2e` |
| V8 | `tests/harness.sh visual` | Playwright projects at 375px and 1280px pass; screenshots classified as intentional or unchanged vs baseline | `bash plans/032/tests/harness.sh visual` |
| V9 | `tests/harness.sh ci-peer-check` | the new peer-validity CI step exits 0 | `bash plans/032/tests/harness.sh ci-peer-check` |

Loop on `bash plans/032/tests/harness.sh all` until every check passes. The harness captures baselines on first run (when `baselines/` is empty) and compares thereafter.

## Out of scope (from plan)

- Redesigning pages.
- Changing URLs or content schema.
- Dependency major upgrades unrelated to audit or peer validity.
- Weakening test/audit gates.
