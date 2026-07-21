# Plan 035: Make Astro page-transition scripts idempotent

> **Executor instructions**: Fix ownership and cleanup for global shell listeners, then prove repeated client-side navigation does not multiply handlers. Do not redesign the shell. Update plan 035 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/components/template/common/BasicScripts.astro src/components/template/navigation/Header.astro src/components/ds/SearchInterface.astro src/layouts tests playwright.config.ts`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/031-enforce-representative-frontend-tests.md
- **Category**: bug
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The global shell reruns initialization after Astro swaps but attaches media-query, scroll, and observer callbacks without a complete ownership/cleanup contract. After repeated client navigation, work and side effects can multiply. The Header and Search components already demonstrate idempotent element binding; the global shell needs the equivalent lifecycle discipline.

## Current state

- `../noticiencias/src/components/template/common/BasicScripts.astro` registers `onLoad` on initial load and every `astro:after-swap`.
- Its `attachEvent` helper has no bound marker, media-query/scroll handlers can be reattached, and `IntersectionObserver` instances are restarted without guaranteed disconnect.
- `../noticiencias/src/components/template/navigation/Header.astro:185-218` uses a dataset bound marker as the local element-binding exemplar.
- `../noticiencias/src/components/ds/SearchInterface.astro:118-130,288-289` uses initialized/bound dataset state with transition rebootstrap.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Static checks | `npm --prefix ../noticiencias run lint` | exit 0 |
| Build/tests | `npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist && npm --prefix ../noticiencias run test:audit` | exit 0 |
| Lifecycle E2E | `CI=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:4321 npm --prefix ../noticiencias run test:e2e -- lifecycle` | repeated navigation assertions pass |

## Scope

**In scope**: `BasicScripts.astro`, only directly affected shell/component bootstraps, and Playwright lifecycle regression tests.

**Out of scope**: ReportForm lifecycle (plan 023), removing Astro ClientRouter, visual redesign, global state libraries, or unrelated component scripts.

## Git workflow

- Branch: `advisor/035-idempotent-astro-scripts` in the frontend repository.
- Commit example: `fix(ui): clean up shell listeners across page swaps`.

## Steps

### Step 1: Give each global resource one owner

List every listener, media-query subscription, observer, timer, and root class mutated by `BasicScripts.astro`. Refactor to a module-scoped singleton state containing installed flag plus cleanup callbacks. Global lifecycle listeners install once; page-element bindings are reacquired after each swap.

**Verify**: a test instrumentation hook reports one global handler per event after initial load and after ten route swaps.

### Step 2: Pair setup and teardown

Use Astro transition lifecycle events to disconnect observers and release only page-scoped resources before the old DOM is discarded. Recreate them against the new document after page load/swap. Use dataset/WeakSet ownership for element callbacks, following Header/Search patterns. Preserve idempotent theme and scroll restoration.

**Verify**: detached nodes have no active observer/listener references after `astro:before-swap`; new nodes work once after `astro:page-load`/equivalent supported event.

### Step 3: Add navigation regression coverage

Create a Playwright test that navigates among home, listing, article, and search through client transitions at least ten times. Instrument callback counts in test mode and assert one invocation per synthetic scroll/media/query event, no duplicate menu/search actions, stable class state, and no console/page errors.

**Verify**: lifecycle-focused E2E passes at 375px and 1280px and fails when the bound guard is removed in a disposable diff.

## Test plan

- Initial direct load and repeated client transitions.
- Back/forward navigation and bfcache-compatible behavior.
- Mobile/desktop media-query transition, scroll-to-top, lazy animation observer, header, and search interactions.
- Console/page-error collection remains empty.

## Done criteria

- [ ] Global listeners are installed once.
- [ ] Every page-scoped observer/listener has explicit cleanup.
- [ ] Ten client transitions do not multiply callback counts.
- [ ] Mobile/desktop interaction tests and full validation pass.

## STOP conditions

- Stop if the exact supported Astro 7 lifecycle differs after plan 032; use the installed version's documented event, not a guessed name.
- Stop if a cleanup would remove a listener owned by another component; establish ownership first.
- Stop if test instrumentation would ship meaningful production overhead; gate it behind build/test mode.

## Maintenance notes

Every transition-aware script must document whether its state is global or page-scoped and pair resource creation with cleanup. Reuse Header/Search binding patterns.

