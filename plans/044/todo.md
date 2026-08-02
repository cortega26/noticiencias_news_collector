# Plan 044 — Running to-do

## Pre-flight
- [x] Read plan 044
- [x] Drift check: `pageSize: 10` hardcoded in `[...page].astro:17`; config says `postsPerPage: 6`
- [x] Branch `advisor/044-pagination-component-pruning` created

## Step 1 — Fix pagination drift
- [x] Replace `pageSize: 10` with `blogPostsPerPage` in `src/pages/blog/[...page].astro`
- [x] Build passes (168 pages, was 166 — more archive pages due to 6 vs 10)
- [x] Commit: `refactor: unify pagination to configured value` (fc883f2)

## Step 2 — Pagination regression test
- [x] Create `tests/pagination-config.test.ts`
- [x] Run V2 (pagination ✓)
- [x] Commit: `refactor: unify pagination to configured value` (fc883f2) — steps 1-2 together

## Step 3 — Component reachability checker
- [x] Create `scripts/check-component-reachability.js` (static import graph, rooted at pages/layouts/config)
- [x] Run checker — found 43 unreachable, but many are false positives (cannot model Astro tag usage); manual verification needed
- [x] Commit: `refactor: remove unreachable components and add reachability checker`

## Step 4 — Delete proven orphans
- [x] Delete 6 manually-verified orphans: WhyTrustUs, EditorialFigure, KeyTakeaways, ArticleSidebar, SinglePost, ToBlogLink (all have zero external references)
- [x] Run V1 (build 168 ✓) + V3 (validate ✓) + V4 (e2e 50 ✓)
- [x] Commit: `refactor: remove unreachable components and add reachability checker`

## Close-out
- [x] Update `plans/README.md` to DONE
- [x] Run full `tests/harness.sh all` green (7/7)
