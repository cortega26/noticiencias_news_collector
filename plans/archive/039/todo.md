# Plan 039 — Running to-do

Status: ` ` = pending · `~` = in progress · `x` = done · `!` = blocked

## Pre-flight

- [x] Read `plans/039-prebuild-browser-search-index.md` in full
- [x] Verify plans 031+032 are DONE (Astro 7 Sätteri Markdown baseline taken post-032)
- [x] Confirm `../noticiencias` exists; branch off plan 035 branch
- [x] Drift check: `git -C ../noticiencias diff --stat 0cdca74..HEAD -- src/pages/search.json.js src/components/common/SearchInterface.astro src/utils/search.ts tests/search-integration.test.ts tests/playwright/search.test.ts package.json package-lock.json scripts`
- [x] Read current `search.json.js` (63 lines, emits per-post `content: post.body`), `SearchInterface.astro:139-165` (browser builds Lunr), `search.ts` (normalizeQuery/normalizeSearchDocument)
- [x] Record baseline: `/search.json` 131KB raw / 45KB gzip, 14 search tests pass

## Step 1 — Record relevance and size baselines

- [x] Capture `/search.json` size (131,767 bytes raw, 45,225 gzip)
- [x] Capture build time (1.44s, 166 pages)
- [x] Capture search unit tests (14 passed)
- [x] Capture e2e search tests (`search index JSON is accessible` passes; `search page loads` fixme)

## Step 2 — Create a pure build-time index generator

- [x] Create `src/utils/build-search-index.ts` (server-only): extract docs, strip Markdown, normalize, build Lunr, serialize `index.toJSON()`, emit versioned artifact `{ version, index, store }`
- [x] Rewrite `src/pages/search.json.js` to emit the versioned artifact
- [x] Expand `tests/search-integration.test.ts` with 4 new serialized-index tests (load, reproduce order, no raw content, deterministic)
- [x] Run V1 (build ✓) + V3 (relevance 18 tests ✓) + V7 (no-raw-body ✓)
- [x] Commit: `perf(search): serialize index at build time` (b2fc4b4) — Steps 2-4 landed together

## Step 3 — Load instead of build in the browser

- [x] Update `SearchInterface.astro`: `fetch → { version, index, store } → lunr.Index.load(index)`, cache module-level promise across transitions
- [x] Add invalid-artifact, version-mismatch, and network-error states
- [x] Run V4 (validate ✓) + V5 (e2e 50 passed ✓)
- [x] Commit: `perf(search): serialize index at build time` (b2fc4b4) — Steps 2-4 landed together

## Step 4 — Add artifact and performance budgets

- [x] Create `scripts/check-search-budget.js`: validate refs, no drafts, deterministic serialization, size budget (gzip < 150KB)
- [x] Run V2 (size ✓ gzip 94KB) + V6 (budget ✓ with regression-injection proof ✓)
- [x] Commit: `perf(search): serialize index at build time` (b2fc4b4) — Steps 2-4 landed together

## Close-out

- [x] Update `plans/README.md` row for plan 039 to DONE
- [x] Run full `tests/harness.sh all` green (10/10 passed, 0 failed)
- [x] ~iteration 20: fresh sub-agent review of spec.md vs implementation (pending)
