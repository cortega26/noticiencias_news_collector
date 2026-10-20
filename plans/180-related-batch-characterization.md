# Plan 180: Characterize the batch related-posts precompute (060 Phase 9, item 2)

> Test-only; run every verification; stop on STOP.
> **Drift check (frontend)**: `git diff --stat c5b51165..origin/main -- src/utils/related.ts tests/related.test.ts`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (tests only)
- **Depends on**: P2-01 ranking (existing)
- **Category**: frontend tests
- **Planned at**: frontend `c5b51165`, backend `d3611776`, 2026-10-20

## Why this matters

Phase 9 item 2 asks to characterize deterministic related-post top-four results
and precompute them. The implementation already:
- ranks with structured signals (`related.ts`), deterministic tie-break by
  publish date, cap, and an explicit recent fallback;
- precomputes once per build via `rankAllRelatedPosts(posts, 4)` in
  `src/pages/[...slug].astro`, memoized with WeakMaps keyed by the post array.

The **single-post** `rankRelatedPosts` is well tested (`tests/related.test.ts`),
but the **batch** function used by the build has no direct test. A regression in
the cache key/cap could change the built related sections without failing a
unit test (the dist test covers only one post). Add the missing characterization;
no production change.

## Scope

**Frontend only**: `tests/related.test.ts` (import `rankAllRelatedPosts` and add
a `describe` block). Do **not** change `src/utils/related.ts`, components,
content or the ranking.

## Steps

1. Add tests to `tests/related.test.ts`:
   - **Equivalence**: `rankAllRelatedPosts(posts, 4)` returns a selection for
     every post, and each equals `rankRelatedPosts(post, posts, 4)` (kind +
     ordered ids).
   - **Determinism**: two consecutive calls with the same array return
     identical kind+ids for every post.
   - **Cap/cache key**: after `rankAllRelatedPosts(posts, 2)`, a `(posts, 4)`
     call still returns up to 4 (and the 2-call returns at most 2); the batch
     cache must not leak the smaller cap.
   - **Tie order**: the batch preserves the newest-first tie order proven by
     the single-post test.
   - Use the existing `makePost` factory; keep all existing tests unchanged.
2. Verify: `npm run test:audit` (≥977 + new), `npm run lint`,
   `npx astro check`, `npm run build` (299 pages), `npm run format:check`.
3. Commit, push, open one PR, wait for checks, merge. Do not leave it open.
4. `plans/060/todo.md`: mark Phase 9 item 2 done with this evidence.

## Done criteria

- [ ] The batch function is directly tested (equivalence, determinism, cap, tie)
- [ ] No production change; existing tests unchanged
- [ ] Lint/check/build/tests/format green; one PR merged
- [ ] 060 item 2 marked done; ledger row 180 updated

## STOP conditions

- The batch and single-post results disagree (report the diverging post and ids;
  do not change the ranking).
- A test needs a production change to pass (STOP).
- The cap test exposes a real cache bug (report; do not paper over it).
