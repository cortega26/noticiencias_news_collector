# Plan 035 — Make Astro page-transition scripts idempotent

> Working folder for the executor. Source of truth: [`plans/035-make-astro-scripts-idempotent.md`](../035-make-astro-scripts-idempotent.md).
> Target repo: `../noticiencias` (Astro frontend). Branch: `advisor/035-idempotent-astro-scripts`.

## Goal

Fix the global shell lifecycle so repeated client-side navigation (Astro View Transitions) does not multiply listeners, observers, or side effects:

1. **Global listeners installed once** — `window.onload`, `window.onpageshow`, media-query `change`, scroll, and the `astro:after-swap` listener itself are installed exactly once, not re-attached per swap.
2. **Page-scoped resources paired with cleanup** — `IntersectionObserver` instances are disconnected before the old DOM is discarded (`astro:before-swap`); element bindings (menu toggle, color-scheme toggle, social share, header scroll) are reacquired against the new DOM after each swap using dataset ownership markers.
3. **Ten client transitions do not multiply callback counts** — a test instrumentation hook (gated behind test mode) reports exactly one invocation per synthetic event after 10 swaps.
4. **Mobile/desktop interaction tests pass** — Playwright lifecycle E2E at 375px and 1280px, with empty console/page-error collection.

## STOP conditions (binding — from plan)

- STOP if the exact supported Astro 7 lifecycle differs after plan 032; use the installed version's documented event, not a guessed name. **Confirmed**: Astro 7.1.3 supports `astro:before-swap`, `astro:after-swap`, `astro:page-load`, and `astro:before-preparation` (per the View Transitions guide). The repo's `Layout.astro` uses `<ClientRouter fallback="swap" />`.
- STOP if a cleanup would remove a listener owned by another component; establish ownership first.
- STOP if test instrumentation would ship meaningful production overhead; gate it behind build/test mode.

## Current state (after plan 032)

`BasicScripts.astro` (286 lines, `src/components/ds/templates/`) has two `<script>` blocks:

**Block 1 (inline, `is:inline` + `define:vars`)**: theme + menu + scroll + share. After plan 032's Rust-compiler fix, the guard is `if (!window.basic_script) { ... }` — so the *entire* block runs once on initial load. But it registers a `document.addEventListener('astro:after-swap', ...)` that calls `initTheme()`, `onLoad()`, `onPageShow()` on every swap. `onLoad()` calls `attachEvent(...)` which does `elem.addEventListener(...)` **without** a dataset bound marker — so after each swap, menu-toggle/color-scheme/share click handlers are re-attached to the same elements (if they survive) or to new elements (if they're recreated). The `window.onload`/`onpageshow` assignments are inside the once-guard, so they're fine.

**Block 2 (module, TS)**: `IntersectionObserver` singleton. `Observer.start()` is called once on initial load and again on every `astro:after-swap`. `start()` creates a **new** `IntersectionObserver` each time without disconnecting the previous one — so after N swaps, there are N observers all watching the same elements, each firing callbacks.

**Exemplars**:
- `Header.astro:187-188`: `if (trigger.dataset.awDropdownBound === 'true') return; trigger.dataset.awDropdownBound = 'true';`
- `SearchInterface.astro:118-130,288`: `if (form.dataset.searchInitialized === currentPath ...)`, `form.dataset.searchBound = 'true'`, `document.addEventListener('astro:page-load', bootSearch);`

## Implementation details

### Step 1 — Give each global resource one owner

Refactor `BasicScripts.astro` Block 1 so:
- The `astro:after-swap` listener is registered **once** (it already is, inside the `if (!window.basic_script)` guard — preserve this).
- `attachEvent` gains a dataset bound marker (`data-aw-bound`) before calling `addEventListener`, following the Header pattern. On re-`onLoad()` after a swap, elements that already have the marker are skipped; new elements (created by the swap) get bound.
- `window.onload` / `window.onpageshow` are assignments (not `addEventListener`), so they're naturally idempotent — preserve.

### Step 2 — Pair setup and teardown for the IntersectionObserver

Refactor `BasicScripts.astro` Block 2 so:
- `Observer.start()` disconnects any existing `this.observer` before creating a new one (`this.observer?.disconnect()`).
- Register an `astro:before-swap` listener (once, at module scope) that calls `Observer.observer?.disconnect()` and clears `Observer.elements`, releasing page-scoped observer references before the old DOM is discarded.
- The existing `astro:after-swap` → `Observer.start()` stays, now safely recreating the observer against the new DOM.
- Preserve `removeAnimationDelay()` (called by the color-scheme toggle in Block 1).

### Step 3 — Add navigation regression coverage

Create `tests/playwright/lifecycle.test.ts` that:
- Navigates home → listing → article → search → home, 10 round-trips, via client-side `<a>` clicks (not `page.goto`, to exercise View Transitions).
- After the 10th swap, injects a synthetic scroll event and asserts the header-scroll handler fires exactly once.
- Asserts no duplicate menu-toggle behavior (click the menu toggle, verify it opens; click again, verify it closes — not a no-op from double-handler).
- Asserts the IntersectionObserver callback count (via a `window.__intersectCount` test hook) is 1 per element after 10 swaps.
- Collects console errors and page errors; asserts both are empty.
- Runs at both `mobile-375` and `desktop-1280` projects.

Gate the test instrumentation behind `import.meta.env.MODE === 'test'` or a `window.__testHooks` sentinel so it ships zero production overhead.

## Verification (how each piece is proved)

| # | Test file | Asserts | Run |
|---|---|---|---|
| V1 | `tests/harness.sh build` | `npm run build` exits 0; route+post count matches baseline (166) | `bash plans/035/tests/harness.sh build` |
| V2 | `tests/harness.sh validate` | lint + validate:content + test:dist + test:audit all pass | `bash plans/035/tests/harness.sh validate` |
| V3 | `tests/harness.sh e2e` | existing e2e suite (46 tests) still passes — no regression | `bash plans/035/tests/harness.sh e2e` |
| V4 | `tests/harness.sh lifecycle` | new lifecycle E2E passes at 375px + 1280px; handler counts are 1 after 10 swaps; console empty | `bash plans/035/tests/harness.sh lifecycle` |
| V5 | `tests/harness.sh regression-injection` | remove the bound guard in a disposable diff, re-run lifecycle, confirm it FAILS (proves the test catches the bug) | `bash plans/035/tests/harness.sh regression-injection` |
| V6 | `tests/harness.sh all` | V1-V4 all green (V5 is a separate proof, not part of `all`) | `bash plans/035/tests/harness.sh all` |

## Out of scope (from plan)

- ReportForm lifecycle (plan 023).
- Removing Astro ClientRouter.
- Visual redesign.
- Global state libraries.
- Unrelated component scripts.
