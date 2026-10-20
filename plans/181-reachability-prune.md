# Plan 181: Prune the dead component cluster and enforce reachability in CI (060 Phase 9, item 1)

> Execute; run every verification; stop on STOP.
> **Drift check (frontend)**: `git diff --stat f09bbab7..origin/main -- scripts/check-component-reachability.js .component-reachability-allowlist.json src/components package.json`

## Status

- **Priority**: P2 (060 Phase 9, item 1)
- **Effort**: M
- **Risk**: MEDIUM-HIGH (deleting components; prove no consumer first)
- **Depends on**: none
- **Category**: frontend dead-code / CI
- **Planned at**: frontend `f09bbab7`, backend `bbdd2869`, 2026-10-20

## Why this matters

The reachability checker (`scripts/check-component-reachability.js`) reports
**27 unreachable components**: 23 in `src/components/template/**` (the dead
AstroWind leftovers) and 4 in `src/components/ds/**` (`Avatar`,
`ArticleHeader`, `DataBox`, `Card`). The checker is not wired into CI, has no
allowlist file, and compares the allowlist against **absolute** paths, so a
repo-relative allowlist would never match. Phase 9 item 1: fix the matching,
review the findings in cohorts, prove no dynamic/MDX consumer, delete only dead
components, and enforce the checker in CI.

Verified today:
- Live routes use `common/`/`ds/` components; e.g. pages import
  `~/components/common/Pagination.astro`, not the dead `template/blog` one.
  `Header`/`Logo`/`ReportForm`/`Toggle*` are live template components and are
  **not** in the finding list.
- Collisions are name-only (`ListItem` = JSON-LD `@type`, `Tags` = prose,
  `Content` = render result), not imports.
- The 4 `ds` components have no consumers except dead template components
  (`Avatar` ← `ArticleHeader`, `DataBox` ← `CredibilitySignals`); `ArticleHeader`
  and `Card` have none. Plan 060 does not name them as migration targets.

## Scope

**Frontend only**: `scripts/check-component-reachability.js`,
`.component-reachability-allowlist.json` (create only if a surviving dynamic
component needs it), `package.json` (script + lint wiring), the 27 component
files, `plans/060/todo.md` (note; reviewer updates the ledger).

**Out of scope**: live template components (`Header`, `Logo`, `ReportForm`,
`ToggleTheme`, `ToggleMenu`, etc.), `common/**`, `ds` components with a live
consumer, content, routes, the admin app.

## Steps

1. **Fix the checker**:
   - compare allowlist entries as **repo-relative POSIX paths** (normalize
     `./`, backslashes; accept `src/...`); keep the file optional;
   - add `"check:reachability": "node scripts/check-component-reachability.js"`
     and run it from `npm run lint` (fast; no network);
   - add a CLI test (temp fixture) proving a relative allowlist entry is
     honored and a missing entry fails — do not weaken the default.
2. **Cohort A — 23 `template/**` components**: for each, prove dead:
   - the checker says unreachable;
   - search actual **imports/usages** (not mere words) across
     `src/pages`, `src/layouts`, `src/components` (live), `src/content`,
     `src/utils`, `scripts`, `astro.config.mjs`, and dynamic patterns
     (`import.meta.glob`, `Astro.glob`, component maps, MDX `components={{}}`);
   - check `src/types.d.ts` for exported types of that component;
   - delete with `git rm` only after the proof. Group the deletions in one
     commit with a list of the proofs.
3. **Cohort B — 4 `ds/**` components**: same proof. Delete them too if they
   have no live consumer (today's evidence says so); if any has a documented
   live/migration consumer, keep it and either fix the checker reachability or
   add a **single** allowlist entry with a one-line reason. Do not bulk
   allowlist.
4. **CI**: ensure `npm run lint` runs the checker (and therefore the frontend
   `validate` job). The gate must be green with the remaining set.
5. Gates: `npm run lint`, `npx astro check`, `npm run build` (299 pages),
   `npm run test:audit` (≥981), `npm run format:check`,
   `npx vitest run` for any new checker test, and the checker exit 0.
6. Commit, push, open **one** PR, wait for checks, merge; do not leave it open.
7. `plans/060/todo.md`: mark Phase 9 item 1 done with the cohort evidence
   (deleted count, allowlist state, CI wiring).

## Done criteria

- [ ] Checker allowlist matching is repo-relative and tested; wired into lint/CI
- [ ] Every deleted component has a recorded no-consumer proof (static/dynamic/MDX/type)
- [ ] No live template/common/ds component deleted; no route/content change
- [ ] Lint/check/build/981 tests/format green; checker exit 0
- [ ] One PR, merged; no open PRs left
- [ ] 060 item 1 marked done; ledger row 181 updated

## STOP conditions

- A component has a live static/dynamic/MDX/type consumer → keep it; if the
  checker misses the live import, fix the checker (report the pattern) instead
  of deleting.
- A deletion changes the built HTML or a test fails → revert that deletion and
  report.
- The 4 `ds` components turn out to be referenced by a documented migration
  target → keep them with individual rationale; do not bulk-allowlist.
- The checker cannot be made deterministic in CI → report.
