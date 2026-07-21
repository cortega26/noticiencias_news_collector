# Plan 039: Ship a prebuilt browser search index

> **Executor instructions**: Preserve ranking, accent/case normalization, result metadata, and no-JavaScript failure messaging while moving index construction to build time. Update plan 039 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/pages/search.json.js src/components/common/SearchInterface.astro src/utils/search.ts tests/search-integration.test.ts tests/playwright/search.test.ts package.json package-lock.json scripts`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/031-enforce-representative-frontend-tests.md, plans/032-migrate-frontend-dependencies.md
- **Category**: perf
- **Planned at**: frontend `0cdca74`, 2026-07-21

## Why this matters

Every search-page visit downloads every post's full Markdown and builds Lunr in the main browser thread before enabling input. That cost grows with the archive and repeats per navigation. Building the serialized Lunr index and a compact result store during Astro build makes search startup a fetch/deserialize operation.

## Current state

- `../noticiencias/src/pages/search.json.js:18-44` emits title/metadata plus complete `post.body` for every article.
- `../noticiencias/src/components/common/SearchInterface.astro:139-165` dynamically imports Lunr, fetches all documents, normalizes them, and builds the index in the browser.
- The input stays disabled until construction completes at lines 136-167.
- `../noticiencias/src/utils/search.ts` owns accent/case normalization and the search document types.
- `../noticiencias/tests/search-integration.test.ts` duplicates the index-building logic instead of testing the emitted artifact.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Search tests | `npm --prefix ../noticiencias run test:audit -- search` | artifact/ranking tests pass |
| Build | `npm --prefix ../noticiencias run build && npm --prefix ../noticiencias run test:dist` | exit 0 and search artifacts exist |
| Browser | `CI=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:4321 npm --prefix ../noticiencias run test:e2e -- search` | accent/case/tag/URL navigation tests pass |
| Budget | `node ../noticiencias/scripts/check-search-budget.js ../noticiencias/dist` | index/store bytes and startup benchmark stay within recorded budgets |

## Scope

**In scope**: build-time normalized search documents, serialized Lunr index, compact result store, browser deserialization, artifact/budget tests, cache/version handling, and search docs.

**Out of scope**: hosted search services, changing public result design, indexing private/draft content, changing canonical URLs, or adding a client framework.

## Git workflow

- Branch: `advisor/039-prebuilt-search-index` in the frontend repository.
- Commit example: `perf(search): serialize index at build time`.

## Steps

### Step 1: Record relevance and size baselines

Capture current `/search.json` compressed/uncompressed size, build time, browser index time on a throttled test profile, and ordered results for a fixed Spanish query corpus covering accents, case, title boosts, descriptions, content, and tags.

**Verify**: baseline fixture is deterministic and every expected URL exists in the current content collection.

### Step 2: Create a pure build-time index generator

Move document extraction/normalization into a typed server/build module. Strip Markdown/MDX syntax to indexable text; omit raw full body from the result store. Build Lunr using the existing fields/boosts, serialize `index.toJSON()`, and emit a versioned artifact containing index plus compact URL-keyed display records (or two cacheable artifacts).

**Verify**: unit tests load the serialized index with `lunr.Index.load()` and reproduce baseline result order for the query corpus.

### Step 3: Load instead of build in the browser

Update `SearchInterface.astro` to fetch/validate the versioned artifact, deserialize it, and keep current safe DOM construction and URL synchronization. Cache the module-level promise/index across Astro transitions; reset only when artifact version changes. Provide explicit loading, empty, invalid-artifact, and network-error states.

**Verify**: browser test shows input becomes enabled after deserialize and no client call to `lunr(function...)` builds documents.

### Step 4: Add artifact and performance budgets

Validate unique canonical refs, no draft/private fields, deterministic serialization, result-store completeness, and an initial size/startup budget based on the measured baseline with a material improvement target. Prefer gzip/Brotli-aware budgets for deployment plus raw-size guardrails.

**Verify**: budget script exits 0 on the real build and fails against an intentionally bloated fixture.

## Test plan

- Pure extraction/Markdown stripping and normalization edge cases.
- Serialize/load equivalence and fixed relevance corpus.
- Browser initial query, accent/case/tag search, no results, artifact failure, page transitions, and result navigation.
- Build artifact uniqueness/privacy/size checks.

## Done criteria

- [ ] The browser does not receive raw full post bodies solely to build search.
- [ ] Lunr indexing occurs at build time and result ordering is preserved.
- [ ] Index/store are validated, cacheable, and versioned.
- [ ] Measured artifact/startup budgets improve and pass.
- [ ] Full frontend validation passes.

## STOP conditions

- Stop if plan 032 changes the content/Markdown processor output; take the search baseline after that migration.
- Stop if serialized Lunr output is nondeterministic across clean builds; sort inputs and isolate the nondeterministic field before gating hashes.
- Stop if relevance fixtures materially regress; do not accept faster but worse search without product approval.

## Maintenance notes

Update the query corpus when fields/boosts change. Budget increases require an archive-size explanation and measured startup evidence.

