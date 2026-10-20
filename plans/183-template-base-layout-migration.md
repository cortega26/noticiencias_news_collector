# Plan 183: Migrate the header/base layout surfaces out of `template/` (+ 9.6 checks)

> Execute; run every verification; stop on STOP. This is the last live
> `template/` surface; after it, only the ADR (9.5) remains before removing the
> layer/guard.
> **Drift check (frontend)**: `git diff --stat 48d39eec..origin/main -- src/layouts src/components/template src/components/common src/components/ds src/utils/images.ts tests scripts/freeze-template.js`

## Status

- **Priority**: P2 (060 Phase 9 items 4+6)
- **Effort**: M-L
- **Risk**: HIGH (every route uses the base layout/header; metadata/visual)
- **Depends on**: 181/182 (dead cluster pruned; leaf surfaces moved)
- **Category**: frontend migration / release proof
- **Planned at**: frontend `48d39eec`, backend `98b4421a`, 2026-10-20

## Why this matters

`BaseLayout` (every page) still imports `layouts/template/Layout.astro` +
`template/widgets/Header.astro`; all `.md` pages use
`layouts/template/MarkdownLayout.astro`; `PostLayout` uses no template now
(182). `PageLayout`/`LandingLayout` have **no page importers** (dead layouts
hidden by the checker's layout roots). Migrating the remaining live surfaces
empties the layer, so 9.5 can supersede the two-layer governance.

## Live inventory (verified)

- `src/layouts/BaseLayout.astro` → `layouts/template/Layout`, `template/widgets/Header`.
- `src/layouts/template/MarkdownLayout.astro` → `BaseLayout` (live), used by
  `metodologia.md`, `nosotros.md`, `recursos/detector-de-hype.md`,
  `patrocinios.md`, `contacto.md`, `transparencia.md`, `privacidad.md`,
  `terminos.md`, `uso-de-ia.astro`.
- `template/Layout` → CommonMeta, CustomStyles, ApplyColorMode, Metadata,
  SiteVerification, Analytics (template) + common Favicons + ds ConsentBanner/
  AnalyticsEvents/BasicScripts.
- `Header` → Logo, ToggleTheme, ToggleMenu (template) + common HeaderSearch +
  ds Button.
- `Logo` → `template/common/Image`; `buildHead`/`seo` are imported by tests and
  metadata components; `utils/images.ts` imports the `OpenGraph` type.
- `PageLayout`/`LandingLayout`: no importers outside `src/layouts/template`.

## Target layout

**Move (git mv, update imports):**
- `layouts/template/Layout.astro` → `src/layouts/Layout.astro`
- `layouts/template/MarkdownLayout.astro` → `src/layouts/MarkdownLayout.astro`
- `components/template/widgets/Header.astro` → `src/components/common/Header.astro`
- `components/template/Logo.astro` → `src/components/common/Logo.astro`
- `components/template/common/{ToggleTheme,ToggleMenu,CommonMeta,CustomStyles,ApplyColorMode,Metadata,SiteVerification,Analytics,Image}.astro`
  → `src/components/common/…` (same names)
- `components/template/common/buildHead.ts`, `seo.ts` →
  `src/components/common/buildHead.ts`, `src/components/common/seo.ts`

**Delete:** `layouts/template/PageLayout.astro`,
`layouts/template/LandingLayout.astro` (no importers; record the grep proof).

**Update imports:** BaseLayout, MarkdownLayout, the 8 md page frontmatter
`layout:` paths, `uso-de-ia.astro`, Header/Logo/Layout internals,
`utils/images.ts` (`OpenGraph` type), `tests/metadata-assembly.test.ts`,
`tests/social/metadata.test.ts`, any docs references. Update
`scripts/freeze-template.js`: remove all moved/deleted entries; leave the guard
in place with a comment that no files remain and the ADR (9.5) removes it.

## Steps

1. Baseline: `npm ci`; `npm run build`; snapshot `dist` HTML hashes (and
   screenshots if Playwright browsers are available); run `npm run test:audit`,
   `npm run test:dist`, metadata tests.
2. Move/delete/update as above. Do not change markup, CSS, logic, prompts or
   content; only paths/imports.
3. `npm run lint` (checker + content + prettier + eslint), `npx astro check`,
   `npm run build` (299 pages), `npm run test:audit`, `npm run test:dist`,
   `npm run check:freeze`, `npm run format:check`.
4. **HTML/metadata proof**: compare before/after built HTML hashes; expect
   identical content modulo a hashed CSS filename (Tailwind scan path). Run the
   metadata/JSON-LD tests; inspect `dist` for `og:image`, canonical URLs and
   JSON-LD on `/`, an article and a tag page.
5. **Visual 375/1280** (9.6): with Playwright (install Chromium if the browsers
   are missing) load `/`, one article, `/categorias/ciencia/`, and
   `/reportar-problema/` at 375×812 and 1280×800; screenshot and compare the
   header/footer/nav layout. If browsers cannot be installed, report the
   limitation and rely on the HTML/metadata proof — do not claim visual proof.
6. Commit, push, open **one** PR, wait for checks, merge. Do not leave it open.
7. `plans/060/todo.md`: mark item 4 done (zero live template consumers) and
   note the 9.6 evidence; item 5 (ADR) remains.

## Done criteria

- [ ] No live import of `src/components/template/**` or `src/layouts/template/**`
- [ ] PageLayout/LandingLayout deleted with a no-importer proof
- [ ] Markdown pages and `uso-de-ia` use the new MarkdownLayout path
- [ ] Build 299 pages, 987+ tests, `test:dist`, metadata tests, checker, freeze green
- [ ] HTML/metadata proof recorded; visual 375/1280 recorded or limitation stated
- [ ] One PR merged; ledger row 183 updated; 060 item 4 closed

## STOP conditions

- A moved component imports something that would create a `common/ds → template`
  dependency → report.
- Built HTML changes beyond a hashed asset name; metadata/canonical/JSON-LD
  differs → revert and report.
- The visual pass shows a header/footer/layout regression → revert and report.
- The freeze script or a test blocks the move for a reason that cannot be fixed
  by updating the allowlist/path → report; never weaken the guard.
