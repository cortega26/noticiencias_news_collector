# Plan 182: Migrate the leaf template surfaces (ReportForm, SocialShare)

> Execute; run every verification; stop on STOP.
> **Drift check (frontend)**: `git diff --stat b7e5ae36..origin/main -- src/components/template/widgets/ReportForm.astro src/components/template/common/SocialShare.astro src/pages/reportar-problema.astro src/layouts/PostLayout.astro scripts/freeze-template.js`

## Status

- **Priority**: P2 (060 Phase 9 item 4, first surfaces)
- **Effort**: S
- **Risk**: LOW (component moves; no logic change)
- **Depends on**: 181 (dead cluster pruned)
- **Category**: frontend migration
- **Planned at**: frontend `b7e5ae36`, backend `ed8c596a`, 2026-10-20

## Why this matters

Phase 9 item 4: inventory live `template` callers and migrate route-sized
surfaces into `ds` or `common`, preserving metadata and shared `Image`
behaviour; `ds` must never import `template`. The live callers today are:

- `BaseLayout` → `layouts/template/Layout` + `template/widgets/Header`
  (the big surface; a separate slice with visual checks);
- `PostLayout` → `template/common/SocialShare` (every article);
- `reportar-problema` → `template/widgets/ReportForm` (the page's main surface);
- `utils/images.ts` → a **type-only** import from `template/common/seo`
  (left for later; no runtime coupling).

This plan moves the two leaf surfaces to `common/`, removing two live
`template` imports with no behaviour change. The header/layout migration stays
for a dedicated slice (visual + metadata proof).

## Scope

**Frontend only**: move
`src/components/template/widgets/ReportForm.astro` →
`src/components/common/ReportForm.astro` and
`src/components/template/common/SocialShare.astro` →
`src/components/common/SocialShare.astro`; update the two imports; remove the
two entries from `scripts/freeze-template.js`.

**Out of scope**: Header/Layout/PageLayout/LandingLayout, `seo.ts`, the
`images.ts` type import, any UI/CSS change, content, routes, admin.

## Steps

1. `git mv` the two components to `common/`.
2. Update `src/pages/reportar-problema.astro` and `src/layouts/PostLayout.astro`
   imports to the new paths.
3. Remove the `ReportForm`/`SocialShare` allowlist entries (and their stale
   comments) from `scripts/freeze-template.js`; do not touch other entries.
4. Verify no `components/template/` import remains from pages/layouts/ds/common
   except the known `seo` type and the header/layout callers.
5. Gates: `npm ci`; `npm run lint` (includes the reachability checker),
   `npx astro check`, `npm run build` (299 pages), `npm run test:audit`
   (≥987), `npm run check:freeze`, `npm run format:check`. Compare built HTML
   hashes before/after if practical (normalize a hashed CSS href if Tailwind
   reorders).
6. Commit, push, open **one** PR, wait for checks, merge. Do not leave it open.
7. `plans/060/todo.md`: note the two surfaces migrated; the item stays open for
   Header/Layout and the SEO type.

## Done criteria

- [ ] The two components live in `common/`; pages/layouts import the new paths
- [ ] No behaviour/logic change; build 299 pages, 987+ tests, checker 0
- [ ] Freeze allowlist no longer names the moved files; `check:freeze` green
- [ ] One PR, merged; no open PRs left
- [ ] Ledger row 182 updated

## STOP conditions

- A moved component imports a template-only helper that would create a
  `common → template` dependency → report (do not move it).
- The build/tests/HTML change beyond a hashed asset name → report.
- The freeze script blocks the move → report (do not weaken it).
