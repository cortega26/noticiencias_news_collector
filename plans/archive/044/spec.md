# Plan 044 — Unify pagination and prune dead components

> Working folder. Source: [`plans/044-unify-pagination-and-prune-dead-components.md`](../044-unify-pagination-and-prune-dead-components.md).
> Target: `../noticiencias`. Branch: `advisor/044-pagination-component-pruning`.

## Goal

1. **One pagination source** — blog/category/tag all use `blogPostsPerPage` (6) from config; no hardcoded `pageSize: 10`.
2. **Regression test** — a test that fails if the route reverts to an inline page size.
3. **Component reachability** — a checker that proves which components are unreachable; only proven-orphans deleted.

## Implementation

### Step 1 — Fix pagination drift (DONE)
`src/pages/blog/[...page].astro` now imports `blogPostsPerPage` from `~/utils/blog` and uses it as `pageSize` instead of hardcoding 10. Build went from 166 to 168 pages (30 posts / 6 = 5 archive pages vs 3).

### Step 2 — Pagination regression test
New `tests/pagination-config.test.ts`: assert blog archive uses configured value.

### Step 3 — Component reachability checker
New `scripts/check-component-reachability.js`: parse static imports from `src/pages/**`, `src/layouts/**`, follow aliases, report unreachable components.

### Step 4 — Delete proven orphans
Delete only components with zero inbound paths from active roots.

## Verification

| # | Test | Asserts | Run |
|---|---|---|---|
| V1 | `tests/harness.sh build` | build exits 0, 168 pages | `bash plans/044/tests/harness.sh build` |
| V2 | `tests/harness.sh pagination` | pagination test passes; reverting to 10 fails | `bash plans/044/tests/harness.sh pagination` |
| V3 | `tests/harness.sh validate` | lint + validate:content + test:dist + test:audit | `bash plans/044/tests/harness.sh validate` |
| V4 | `tests/harness.sh e2e` | existing e2e passes | `bash plans/044/tests/harness.sh e2e` |
| V5 | `tests/harness.sh all` | V1-V4 green | `bash plans/044/tests/harness.sh all` |
