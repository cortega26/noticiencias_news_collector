# Plan 044: Unify configured pagination and prune unreachable frontend components

> **Executor instructions**: Fix the observable pagination drift first, then prove component reachability before deleting anything. Do not treat filename searches alone as a safe deletion test. Update plan 044 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/config.yaml src/utils/blog.ts src/pages/blog/'[...page].astro' src/components tests package.json`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: plans/031-enforce-representative-frontend-tests.md, plans/032-migrate-frontend-dependencies.md
- **Category**: maintainability
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

The archive route silently paginates at 10 items while the site configuration says 6 and the category/tag helpers use the configured value. At the same time, several Astrowind-era component subgraphs have no inbound path from a page, layout, content file, or active component. A single pagination source and a repeatable reachability proof remove behavior drift and reduce the surface future migrations must carry.

## Current state

- Frontend `src/config.yaml` defines `apps.blog.postsPerPage: 6`; `src/utils/blog.ts:206` exports that value and uses it in blog/category/tag pagination helpers.
- `src/pages/blog/[...page].astro:11-18` bypasses the helper and hardcodes `pageSize: 10`.
- `tests/category-static-paths.test.ts:13-25,40-57` replaces the real value with 10, so it cannot catch drift from the configured 6.
- Exact import/reachability inspection found no inbound active roots for `WhyTrustUs.astro`, `EditorialFigure.astro`, `KeyTakeaways.astro`, `ArticleSidebar.astro`, `SinglePost.astro`, `ToBlogLink.astro`, and template `Pagination.astro`.
- It also found isolated subgraphs `List.astro` -> `ListItem.astro`, `Features2.astro` -> `ItemGrid2.astro`, and `BlogHighlightedPosts.astro` -> `Grid.astro` -> `GridItem.astro`. These are deletion candidates, not permission to delete before the automated graph and production build agree.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `npm --prefix ../noticiencias run test:audit -- tests/pagination-config.test.ts tests/component-reachability.test.ts` | configured page sizes and reachability fixtures pass |
| Reachability check | `npm --prefix ../noticiencias run check:component-reachability` | no unapproved unreachable component/subgraph is reported |
| Baseline gates | `npm --prefix ../noticiencias run lint && npm --prefix ../noticiencias run validate:content` | exit 0 |
| Full frontend gates | `npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist && npm --prefix ../noticiencias run test:audit` | build, dist sanity, and all Vitest tests pass |

## Scope

**In scope**: one configured pagination path for blog/category/tag routes, tests that read or faithfully fixture the production value, a static component-import reachability checker, an explicit dynamic/content allowlist, deletion of proven unreachable component subgraphs, and affected documentation.

**Out of scope**: visual redesign, changing `postsPerPage` from 6, deleting components merely because CodeGraph cannot resolve Astro imports, converting the design system, or removing components referenced dynamically/through content.

## Git workflow

- Branch: `advisor/044-pagination-component-pruning` in the frontend repository.
- Commit example: `refactor: unify pagination and remove unreachable components`.
- Keep the pagination correction and proven deletions in separately reviewable commits.

## Steps

### Step 1: Make configuration the only pagination authority

Replace the archive route's inline pagination with `getStaticPathsBlogList` or the same exported configured value already used by category/tag helpers. Remove stale comments that name old line numbers. Do not duplicate the config in a route constant.

**Verify**: with 13 fixture posts and `postsPerPage: 6`, blog/category/tag pagination yields 6/6/1 data lengths and correct first/last/prev/next URLs.

### Step 2: Strengthen pagination tests against production-shaped config

Add `tests/pagination-config.test.ts` or expand the existing suite to assert every public listing consumes the same value. If config must be mocked, derive the mock from one named fixture equal to the parsed production setting and separately assert production remains 6. Cover empty taxonomy, exact-boundary, final partial page, and stable ordering.

**Verify**: changing only the route back to 10 makes the focused test fail with the route and expected configured value.

### Step 3: Build a conservative component reachability graph

Add a read-only checker rooted at `src/pages/**`, `src/layouts/**`, integration/config entries, and explicit content component entrypoints. Parse static imports for `.astro`, `.ts`, and `.js`; model path aliases; follow imported subgraphs; and support a reviewed allowlist for dynamic imports or externally consumed components. Report the shortest reason/path for reachable nodes and the isolated subgraph for unreachable nodes.

**Verify**: fixtures cover direct import, alias import, nested import, content/dynamic allowlist, cycle, and a truly orphaned pair. The checker must fail on the orphan and pass on the allowed dynamic entry.

### Step 4: Delete only the intersection of all proofs

Re-run the graph on the post-migration tree, inspect each reported subgraph, and delete only candidates with no active root and no configuration/content/external consumer. Start with the candidates listed above; retain and annotate any disproven candidate. Remove now-unused assets, types, and imports only when they belong exclusively to a deleted subgraph.

**Verify**: reachability check has no unapproved findings; TypeScript/Astro build and all tests pass; generated routes/counts are unchanged except archive page boundaries now follow 6.

### Step 5: Perform required visual/interaction verification

Check archive, one category, one tag, one article, and home at 375px and 1280px. Exercise previous/next links across a partial last page and Astro transitions. Confirm headings, images, canonicals, and console remain clean.

**Verify**: capture the URLs and viewport results in the PR; no deleted component markup appears on any generated page.

## Test plan

- Unit tests for configuration flow and component graph parsing.
- Route pagination tests for 0, 1, 6, 7, 12, and 13 posts.
- Full lint/content/build/dist/Vitest gates.
- Manual 375px/1280px smoke of listings and representative article/home surfaces.

## Done criteria

- [ ] Blog, category, and tag pagination use one configured value.
- [ ] A regression to an inline page size fails focused tests.
- [ ] Component deletions are backed by repeatable reachability evidence and a green production build.
- [ ] No active route, layout, content, dynamic entrypoint, or asset is broken.
- [ ] Required automated and manual frontend validation passes.

## STOP conditions

- Stop deleting if a candidate is referenced by dynamic import, MD/MDX content, integration configuration, package export, or an external consumer.
- Stop if the reachability parser cannot model Astro/alias imports without false negatives; fix the proof or keep the component.
- Stop if plan 032 changes component/layout entrypoints; re-run the drift audit on the migrated tree first.

## Maintenance notes

Run the reachability check in the canonical frontend verification command from plan 041. New dynamic component registries must update the explicit root/allowlist with an owner and reason.
