# Plan 179: Remove the verified-unused frontend dependencies (060 Phase 9, item 3)

> Execute; run every verification; stop on STOP.
> **Drift check (frontend)**: `git diff --stat 7ff45dae..origin/main -- package.json package-lock.json astro.config.mjs`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: frontend dependencies
- **Planned at**: frontend `7ff45dae`, backend `826bc588`, 2026-10-20

## Why this matters

060 Phase 9 asks to remove verified-unused dependencies before changing UI
governance. Verified today:

- `@iconify-json/flat-color-icons` is configured in `astro.config.mjs:56-66`
  but **no component uses any `flat-color-icons:` icon** (grep over `src/` is
  empty).
- `@types/glob` and `ts-node` are devDependencies with no usage in configs,
  scripts, tests or source.
- `astro-embed` (the fourth item in the 060 note) is already absent.

## Scope

**In frontend**: `package.json`, `package-lock.json` (via npm), and the unused
`flat-color-icons` block in `astro.config.mjs`.

**Out of scope**: any other dependency, icon set, config, content, or UI.

## Steps

1. `npm ci`; `npm uninstall @iconify-json/flat-color-icons @types/glob ts-node`.
2. Remove the `'flat-color-icons': [...]` entry from the `icon({ include })`
   block; keep `tabler: ['*']` and the rest untouched.
3. Verify:
   - `npm run lint`, `npx astro check`, `npm run build` (299 pages),
     `npm run test:audit` (≥977), `npm run format:check`;
   - `grep -rn "flat-color-icons" src astro.config.mjs` → 0;
   - the lock diff only removes the three packages and their orphaned
     transitive entries (no version churn elsewhere).
4. Commit, push, open one PR, wait for checks, merge. Keep the PR open only
   until green (no accumulation).
5. `plans/060/todo.md`: mark Phase 9 item 3 done (three removed; `astro-embed`
   already absent).

## Done criteria

- [ ] The three packages and the flat-color-icons config are gone
- [ ] No `flat-color-icons:` reference remains
- [ ] Lint/check/build/tests/format green; lock diff scoped
- [ ] One PR, merged; no open PRs left
- [ ] Ledger row 179 updated

## STOP conditions

- Any component/build references the icon set → report; keep the package.
- Removing a dev dep breaks a tool (e.g. ts-node in a script) → report.
- The lock diff includes unrelated upgrades → stop and report.
