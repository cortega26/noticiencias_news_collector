# Plan 035 — Running to-do

Status: ` ` = pending · `~` = in progress · `x` = done · `!` = blocked

## Pre-flight

- [x] Read `plans/035-make-astro-scripts-idempotent.md` in full
- [x] Verify plan 032 is DONE (Astro 7.1.3 lifecycle events confirmed: `astro:before-swap`, `astro:after-swap`, `astro:page-load`)
- [x] Confirm `../noticiencias` exists and is on `main` (plan 032 branch is separate)
- [x] Drift check: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/components/ds/templates/BasicScripts.astro src/components/template/widgets/Header.astro src/components/common/SearchInterface.astro src/layouts tests playwright.config.ts`
- [x] Read current `BasicScripts.astro` (post-032), Header pattern (`dataset.awDropdownBound`), SearchInterface pattern (`dataset.searchBound`)
- [x] Create branch `advisor/035-idempotent-astro-scripts` in frontend repo (branched off plan 032 branch since 035 depends on 032's Astro 7 lifecycle)
- [x] Record baseline: build (166 pages), e2e (46 passed)

## Step 1 — Give each global resource one owner

- [x] Add dataset bound marker (`data-aw-bound`) to `attachEvent` in BasicScripts.astro Block 1, plus `__awBound` property flag for non-element targets (document)
- [x] Verify `astro:after-swap` listener is registered once (already inside `if (!window.basic_script)` guard)
- [x] Run V1 (build ✓) + V3 (e2e ✓)
- [x] Commit: `fix(ui): clean up shell listeners across page swaps` (96f46b8) — Steps 1-3 landed together

## Step 2 — Pair setup and teardown for IntersectionObserver

- [x] Add `Observer.observer?.disconnect()` at start of `Observer.start()` before creating new observer
- [x] Register `astro:before-swap` listener (once, module scope) that disconnects observer + clears elements
- [x] Preserve `removeAnimationDelay()` and existing `astro:after-swap` → `Observer.start()`
- [x] Run V1 + V3
- [x] Commit: `fix(ui): clean up shell listeners across page swaps` (96f46b8) — Steps 1-3 landed together

## Step 3 — Add navigation regression coverage

- [x] Create `tests/playwright/lifecycle.test.ts`: 3 tests (no-errors, menu-toggle, observer-count) at 375px + 1280px
- [x] Gate instrumentation behind test-mode `addInitScript` (zero production overhead)
- [x] Run V4 (lifecycle at 375px + 1280px ✓) + V5 (regression-injection — inject TS-in-inline-script bug, lifecycle test correctly fails ✓)
- [x] Commit: `fix(ui): clean up shell listeners across page swaps` (96f46b8) — Steps 1-3 landed together

## Close-out

- [x] Update `plans/README.md` row for plan 035 to DONE
- [x] Run full `tests/harness.sh all` green (8/8 passed, 0 failed)
- [x] ~iteration 20: fresh sub-agent review of spec.md vs implementation (pending — will do after close-out)
