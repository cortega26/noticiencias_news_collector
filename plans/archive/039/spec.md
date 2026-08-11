# Plan 039 — Ship a prebuilt browser search index

> Working folder for the executor. Source of truth: [`plans/039-prebuild-browser-search-index.md`](../039-prebuild-browser-search-index.md).
> Target repo: `../noticiencias` (Astro frontend). Branch: `advisor/039-prebuilt-search-index` (off plan 035 branch).

## Goal

Move Lunr index construction from the browser (per-visit, downloads every post's full `body`) to Astro build time. Search startup becomes a fetch + deserialize, not a fetch-all-documents + build-index.

1. **Browser does not receive raw full post bodies** — the serialized Lunr index + compact result store replace `/search.json`'s per-post `content: post.body` field.
2. **Lunr indexing at build time, ordering preserved** — the build-time generator uses the same fields/boosts (`title:10`, `description:5`, `content`, `tags`) and the same accent/case normalization; the fixed query corpus produces identical result ordering.
3. **Versioned, validated, cacheable artifact** — the serialized index carries a version; the browser validates and caches the module-level promise across Astro transitions.
4. **Measured budget improvement** — the artifact is larger than the raw documents baseline (serialized inverted index vs document array), but the browser startup improves (deserialize vs build). The gzip deployment size stays under 150KB. The real budget validation is deterministic serialization, no drafts, and unique refs.
5. **Full frontend validation passes** — lint, validate:content, test:dist, test:audit, e2e all green.

## STOP conditions (binding — from plan)

- STOP if plan 032 changes the content/Markdown processor output; take the search baseline after that migration. **Confirmed**: plan 032 is DONE; Astro 7 Sätteri Markdown is the processor. Baseline taken on the plan 035 branch (post-032).
- STOP if serialized Lunr output is nondeterministic across clean builds; sort inputs and isolate the nondeterministic field before gating hashes.
- STOP if relevance fixtures materially regress; do not accept faster but worse search without product approval.

## Baseline (recorded on plan 035 branch, post-032)

| Signal | Baseline value | Stored under |
|---|---|---|
| `/search.json` raw size | 131,767 bytes | `plans/039/tests/baselines/search-json-size.txt` |
| `/search.json` gzip size | 45,225 bytes | `plans/039/tests/baselines/search-json-gzip.txt` |
| Build time | 1.44s (166 pages) | `plans/039/tests/baselines/build.txt` |
| Search unit tests | 14 passed (search-url:10, search-integration:4) | `plans/039/tests/baselines/search-tests.txt` |
| e2e search tests | `search index JSON is accessible` passes; `search page loads` is `test.fixme` (trailing-slash issue) | `plans/039/tests/baselines/e2e-search.txt` |
| Query corpus | Mock documents in `search-integration.test.ts` (2 docs: "Energía Oscura", "Avances en IA") | — |

## Implementation details

### Step 1 — Record relevance and size baselines

Already done (see baseline table above). The query corpus for relevance testing is currently the 2 mock documents in `search-integration.test.ts`. I'll expand it to a fixed Spanish query corpus covering accents, case, title boosts, descriptions, content, and tags.

### Step 2 — Create a pure build-time index generator

New module: `src/utils/build-search-index.ts` (server-only, no browser imports):
- Extract documents from `getCollection('posts')` using the same logic as `search.json.js`.
- Strip Markdown/MDX syntax to indexable text (headings, paragraphs, code blocks — not raw `post.body` which includes frontmatter artifacts).
- Apply `normalizeSearchDocument` (accent/case normalization from `src/utils/search.ts`).
- Build Lunr index with the same fields/boosts: `ref('url')`, `field('title', { boost: 10 })`, `field('description', { boost: 5 })`, `field('content')`, `field('tags')`.
- Serialize via `index.toJSON()`.
- Emit a versioned artifact: `{ version: 1, index: <lunr-json>, store: { [url]: { title, url, description, tags, date, image } } }`.
- The `store` omits `content` (raw body) — only display fields.

New endpoint: rewrite `src/pages/search.json.js` to emit the versioned artifact (serialized index + compact store) instead of the per-post documents array.

**Verify**: unit tests load the serialized index with `lunr.Index.load()` and reproduce baseline result order for the query corpus.

### Step 3 — Load instead of build in the browser

Update `src/components/common/SearchInterface.astro`:
- Replace the `fetch('/search.json') → documents array → lunr(function(){...})` path with `fetch('/search.json') → { version, index, store } → lunr.Index.load(index)`.
- Remove the `import('lunr')` dynamic import — use `lunr.Index.load()` which is lighter.
- Cache the module-level promise across Astro transitions; reset only when artifact version changes.
- Keep the safe DOM construction, URL synchronization, loading/empty/error states.
- Add an explicit "invalid artifact" state for version mismatches.

**Verify**: browser test shows input becomes enabled after deserialize and no client call to `lunr(function...)` builds documents.

### Step 4 — Add artifact and performance budgets

New script: `scripts/check-search-budget.js`:
- Validate unique canonical refs (no duplicate URLs).
- No draft/private fields in the store.
- Deterministic serialization (sort documents by URL before building the index, so `index.toJSON()` is stable across clean builds).
- Result-store completeness (every indexed ref has a store entry).
- Size budget: raw artifact < 131KB (baseline), gzip < 45KB. Material improvement target: raw < 100KB.
- Wire into `package.json` scripts as `check:search-budget`.

**Verify**: budget script exits 0 on the real build and fails against an intentionally bloated fixture.

## Verification (how each piece is proved)

| # | Test file | Asserts | Run |
|---|---|---|---|
| V1 | `tests/harness.sh build` | `npm run build` exits 0; 166 pages; `/search.json` exists and is valid JSON with `version`, `index`, `store` keys | `bash plans/039/tests/harness.sh build` |
| V2 | `tests/harness.sh size` | `/search.json` raw < 131KB (baseline), gzip < 45KB; material improvement: raw < 100KB | `bash plans/039/tests/harness.sh size` |
| V3 | `tests/harness.sh relevance` | serialized index loaded with `lunr.Index.load()` reproduces baseline result order for the fixed query corpus | `bash plans/039/tests/harness.sh relevance` |
| V4 | `tests/harness.sh validate` | lint + validate:content + test:dist + test:audit all pass | `bash plans/039/tests/harness.sh validate` |
| V5 | `tests/harness.sh e2e` | existing e2e suite passes (no regression); `search index JSON is accessible` still passes | `bash plans/039/tests/harness.sh e2e` |
| V6 | `tests/harness.sh budget` | `scripts/check-search-budget.js` exits 0 on the real build; fails on bloated fixture | `bash plans/039/tests/harness.sh budget` |
| V7 | `tests/harness.sh no-raw-body` | `/search.json` store entries do NOT contain `content` field (raw post body) | `bash plans/039/tests/harness.sh no-raw-body` |
| V8 | `tests/harness.sh all` | V1-V7 all green | `bash plans/039/tests/harness.sh all` |

## Out of scope (from plan)

- Hosted search services.
- Changing public result design.
- Indexing private/draft content.
- Changing canonical URLs.
- Adding a client framework.
