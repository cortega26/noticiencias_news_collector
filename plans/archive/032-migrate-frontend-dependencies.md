# Plan 032: Migrate the frontend to a supported dependency graph

> **Executor instructions**: Land compatible security patches before the framework major; take and compare visual/browser baselines around the Astro migration. Do not suppress peer-dependency errors. Update plan 032 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- package.json package-lock.json astro.config.mjs tailwind.config.js src/layouts src/components/template/common src/utils/images.ts src/styles tests`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/026-pin-github-actions.md, plans/031-enforce-representative-frontend-tests.md
- **Category**: migration
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The installed Astro 6 graph contains production advisories and integrations whose peer ranges stop at Astro 5. Astro 7 is current and changes the compiler, Markdown pipeline, Vite major, and whitespace behavior, so this should be a controlled migration with browser evidence—not another forced invalid install.

## Current state

- `../noticiencias/package.json` and `package-lock.json` resolve Astro 6.4.8, while installed `@astrojs/tailwind`, `@astrolib/analytics`, and `@astrolib/seo` declare peers only through Astro 5.
- `../noticiencias/astro.config.mjs` registers `@astrojs/tailwind`, MDX, sitemap, and icon integrations.
- `../noticiencias/src/components/template/common/Metadata.astro` delegates tags to `@astrolib/seo`; `src/utils/images.ts` imports its OpenGraph type.
- `../noticiencias/src/components/template/common/Analytics.astro` delegates Google Analytics to `@astrolib/analytics`.
- `../noticiencias/src/layouts/template/Layout.astro` owns the metadata and analytics composition path.
- Official references: [Astro 7 migration guide](https://docs.astro.build/en/guides/upgrade-to/v7/) and [Astro styling/Tailwind guide](https://docs.astro.build/en/guides/styling/).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Dependency graph | `npm --prefix ../noticiencias ci && npm --prefix ../noticiencias ls` | exit 0, no invalid peers |
| Audit | `npm --prefix ../noticiencias audit --omit=dev` | zero high/critical production advisories |
| Full validation | `npm --prefix ../noticiencias run lint && npm --prefix ../noticiencias run validate:content && npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist && npm --prefix ../noticiencias run test:audit` | exit 0 |
| Browser | `CI=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:4321 npm --prefix ../noticiencias run test:e2e` | all required local tests pass at 375px and 1280px projects |

## Scope

**In scope**: compatible production security updates, Astro and official integrations, Tailwind integration/config/style migration if required, removal/replacement of unsupported Astrolib wrappers, metadata/image types, lockfile, and migration regression tests.

**Out of scope**: redesigning pages, changing URLs/content schema, dependency major upgrades unrelated to audit or peer validity, or weakening test/audit gates.

## Git workflow

- Branch: `advisor/032-supported-frontend-graph` in the frontend repository.
- Prefer two commits: compatible advisory fixes, then Astro/integration migration.
- Commit example: `build: migrate frontend to supported Astro graph`.

## Steps

### Step 1: Capture the baseline and apply compatible security fixes

Save `npm ls`, production audit JSON, build output, representative screenshots at 375px/1280px, canonical/meta/JSON-LD snapshots, generated post count, and search smoke results. Apply non-major fixes for affected packages such as RSS/transitive archive/YAML packages when the lock can do so without invalid peers.

**Verify**: full validation and browser commands still pass; audit severity is reduced and the remaining graph is documented before the major.

### Step 2: Remove unsupported third-party wrappers

Implement the site's existing metadata contract directly in `Metadata.astro` using escaped Astro attributes and the safe JSON-LD helper from plan 022. Preserve title, description, canonical, robots, Open Graph, Twitter, hreflang, and structured-data output exactly. Replace `@astrolib/analytics` with the minimal component-scoped production-only script that preserves consent/current ID behavior. Replace external SEO types with a local narrow type. Remove both Astrolib packages only after tests compare output.

**Verify**: `rg -n "@astrolib/(seo|analytics)" ../noticiencias/src ../noticiencias/package.json` → no matches; metadata/browser tests pass.

### Step 3: Move Tailwind to a supported integration

Follow the official Astro styling guide. Prefer Tailwind 4 with `@tailwindcss/vite` only after auditing config plugins, custom tokens, `@apply`, Typography, and Forms compatibility. Use the official upgrade tool where appropriate, inspect every generated diff, and migrate global imports/config intentionally. Do not retain `@astrojs/tailwind` on an unsupported peer range.

**Verify**: `npm ls` has no peer errors; visual comparison at 375px and 1280px finds no unintended layout, typography, focus, dark-mode, or responsive regression.

### Step 4: Upgrade Astro and official integrations together

Use the official v7 guide. Account explicitly for Vite 8, the stricter Rust compiler, reserved `src/fetch.ts`, the Sätteri Markdown default, and `compressHTML: 'jsx'`. Because this repository uses MDX/content processing, preserve the unified pipeline if current remark/rehype behavior is required; otherwise prove equivalent rendered output. Set `compressHTML: true` temporarily only if baseline whitespace relies on v6 behavior and add a follow-up note.

**Verify**: clean `npm ci`, `npm ls`, full validation, and local browser tests all pass; generated route/post counts and representative article HTML match intended baseline.

### Step 5: Close audit and compatibility gates

Update audit allowlists only by removing resolved exceptions. Add a CI peer-validity check and document the supported Node/Astro/Tailwind matrix.

**Verify**: production audit has zero high/critical findings, no expired exception, and `npm ls` exits 0.

## Test plan

- Metadata snapshots and DOM assertions before/after wrapper removal.
- Build representative MDX articles containing headings, inline elements, images, code, and custom plugins.
- Browser screenshots/interactions at 375px and 1280px across home, listing, article, search, and error routes.
- Audit, peer graph, content validation, dist validation, and route-count comparisons.

## Done criteria

- [ ] Production dependency audit has no unapproved high/critical advisory.
- [ ] Installed packages have no invalid Astro peer.
- [ ] Unsupported Astrolib dependencies are removed without metadata loss.
- [ ] Tailwind is integrated through a supported path.
- [ ] Astro 7 migration behaviors are explicitly tested and full validation passes.

## STOP conditions

- Stop if plan 031's fail-closed local browser suite is not available.
- Stop if current MDX output cannot be reproduced; preserve the old processor explicitly and report the blocking plugin.
- Stop if a security fix requires a public URL/content-schema change.
- Stop if visual differences cannot be classified as intentional using baseline screenshots.

## Maintenance notes

Keep the official migration guide linked in the PR. Future framework majors require `npm ls`, rendered-content comparisons, and mobile/desktop evidence, not only a successful build.

