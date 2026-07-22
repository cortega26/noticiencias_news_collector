# Plan 037: Make bulk article persistence set-based — spec

## Goals

Reduce `save_articles_bulk()`'s per-article DB round trips (currently: one
URL-exists query, one content-hash query, and `_assign_cluster()`'s up to
3 prefix queries + a possible fallback query, per article) to a small,
roughly batch-size-independent number of queries, while producing
**exactly the same** exact/content/near-duplicate outcomes, cluster
membership, confidence scores, and atomic rollback behavior as today.

## Empirical investigation done before writing any code

The plan's Step 4 asks the batched version to let "later rows in the same
input batch join [a near-duplicate's] cluster exactly as sequential
insertion would." Two closely-related questions had to be answered
empirically, not assumed, before any refactor:

**Q1: does *current* `save_articles_bulk()` already join two near-duplicate
articles submitted in the same batch?** Tested directly: two articles with
near-identical content (simhash hamming distance 4, well under the default
threshold of 10) submitted in one `save_articles_bulk()` call got **two
different cluster_ids** and `duplication_confidence=0.0` on both. Root
cause: `SessionLocal` is built with `autoflush=False`
(`database.py:229`), and `save_articles_bulk` only flushes every
`batch_size` (default 50) items — so `_assign_cluster`'s live
`session.query(Article)` can't see an earlier, not-yet-flushed article
from the same batch as a candidate.

**Q2: is that the correct "sequential" oracle, or is current bulk itself
already diverging from what single-item `save_article()` does?** Tested
directly: the same two near-duplicate payloads run through
`save_article()` *twice* (i.e. genuinely sequential, matching the plan's
"exactly as sequential insertion would" language) **do** join — both end
up with the same `cluster_id`, and *both* rows end up with
`duplication_confidence=0.9375` (proving `_assign_cluster`'s back-mutation
of the matched candidate's confidence is real and persists).

**Conclusion**: current bulk's failure to join same-batch near-duplicates
is a real gap relative to the single-save oracle the plan's Done Criteria
("Single/bulk dedupe and clustering outcomes remain equivalent") and
Step 4's Verify section explicitly target. Building the in-memory
candidate map so same-batch near-duplicates join (Step 4, as literally
written) is the task, not a semantics change to avoid under STOP
condition 2. STOP condition 2 guards against *accidental* drift in
already-persisted-candidate matching (batched prefetch producing a
different match than a live per-item query would) — it does not prohibit
closing this gap, which the plan explicitly asks for.

**A related, pre-existing asymmetry noted but NOT touched**:
`save_article()` (single-item path only) calls `self._revalidate_cluster()`
after flush, which re-examines every article in the assigned cluster and
splits off any whose simhash distance from the cluster's anchor exceeds
`2 * simhash_threshold`. `save_articles_bulk()` has never called this
(confirmed: not present anywhere in the current bulk loop, and not
mentioned in the plan's own "Current state" section). This plan's Step 4
Verify text is specifically about cluster *assignment* equivalence (which
cluster a new row lands in and at what confidence), not this separate
post-hoc integrity/split invariant — extending `_revalidate_cluster` to
bulk is out of scope (not in the plan's Current State/Steps, and the
plan's own Scope section excludes "single-article save behavior").

## Design

### Step 1 — characterization fixtures

`tests/unit/storage/test_bulk_persistence_parity.py`: instruments
SQLAlchemy's `before_cursor_execute` event to count/classify SELECT
statements on a real sqlite `DatabaseManager` (not mocks — the plan 036
review's `PendingRollbackError` finding is a standing reminder that mocks
cannot catch real session/transaction behavior). Records baseline SELECT
counts for a 100-row batch on **current** code before any refactor.

The load-bearing fixture (per the empirical investigation above): two
near-duplicate articles in one `save_articles_bulk()` call must produce
cluster membership/confidence **equal to** two sequential
`save_article()` calls — this is written to fail against current bulk
code first, then made to pass by the Step 4 rewrite.

### Step 2 — normalize/dedupe input once

Extract a `_prepare_bulk_row()` helper: validates/converts each input to
`CollectorArticleModel`, canonicalizes the URL, normalizes
published_date timezone, computes `normalize_article_text` /
`sha256_hex` / `simhash64` / prefix exactly once per valid input. Applies
in-batch URL and content-hash dedup in stable input order (first
occurrence wins, matching current `seen_urls` behavior — extended to
content hashes, which current code does *not* dedupe in-batch, only
against the DB per item; verified this is a genuine gap the plan's Step 2
explicitly asks to close, not a behavior to preserve as-is).

### Step 3 — chunked exact-duplicate prefetch

Two `IN`-chunked queries (reusing `articles_exist()`'s existing
`CHUNK_SIZE=500` pattern) — one for canonical URLs, one for non-null
content hashes — across the whole prepared, deduped row set. Filters
before any `Article()` construction.

### Step 4 — near-duplicate candidate prefetch + in-memory clustering

`_assign_cluster()`'s query portion and decision portion are split:

- `_pick_best_cluster(candidates, simhash_value, published_date)` — pure
  decision logic (hamming filter, `sort_key` tie-break, mutation of the
  matched candidate's `cluster_id`/`duplication_confidence`), extracted
  unchanged from `_assign_cluster` so both the live single-query path and
  the batched in-memory path share **one** implementation — eliminates
  the risk of the two paths silently drifting.
- One prefetch query per bulk call: `Article.simhash_prefix.in_(union of
  every prefix/prefix±1 needed across the batch)`, chunked at the same
  500-item `IN` bound, ordered by `collected_date desc`, grouped into a
  `dict[prefix -> list[Article]]` in memory.
- A **lazy, memoized** fallback query (all non-null-simhash articles,
  recency-ordered, window-limited) — computed at most once per bulk call,
  reused by any item whose own prefix±1 group has zero prefetched
  candidates. Preserves per-item correctness (each item still only
  considers its own valid candidate set) while bounding total queries.
- Each newly-constructed (not yet flushed) `Article` is added to the
  in-memory `dict[prefix -> ...]` map immediately after `session.add()`,
  so a later row in the *same* batch can match it — this is what closes
  the Q1/Q2 gap. Because the map holds the real, mutable ORM instances
  (not copies), a later same-batch row's back-mutation of an earlier
  same-batch row's `duplication_confidence`/`cluster_id` flows through
  SQLAlchemy's session identity map exactly like the single-item path.
- **Tie-break for not-yet-flushed candidates**: `_assign_cluster`'s
  `sort_key` uses `-int(cand_id)` so the most-recently-inserted candidate
  wins hamming/time ties. A not-yet-flushed `Article` has no real `id`
  yet. A per-batch monotonically increasing synthetic id (starting well
  above any real autoincrement value, one per newly-added row in
  insertion order) stands in, so same-batch ties resolve the same way a
  real sequential insert-with-immediate-flush would (later-added wins), and
  any same-batch candidate outranks any already-persisted candidate in a
  tie (matching "just inserted, most recent").

### Step 5 — preserve atomic flush/commit, add the benchmark

`save_articles_bulk`'s existing flush-per-`batch_size`-then-final-commit
structure, and its `except Exception: session.rollback(); raise` (not a
`return False` — this path already re-raises, so it does **not** have the
plan-036-review's `PendingRollbackError` bug; left unchanged) are
preserved untouched. `scripts/benchmark_bulk_persistence.py`: deterministic
100-article synthetic batch (including in-batch exact and near
duplicates), reports prepared/skipped/saved counts and SELECT statement
totals, asserts the count stays within the documented bound.

## Verification

- `pytest tests/unit/storage/test_bulk_persistence_parity.py -q` — query
  counts scale by chunk not article count; single-save vs. batch cluster
  parity (including the same-batch near-duplicate case); atomic rollback
  under a forced unique collision leaves zero partial rows.
- `pytest tests/integration/test_database.py tests/unit/test_database_race_conditions.py tests/test_database_simhash_behavior.py -q`
  — existing behavior unchanged.
- `python scripts/benchmark_bulk_persistence.py --articles 100 --max-selects <N>`
  — exit 0.
- `make lint && make type` — no new findings vs. baseline.
- `pytest --ignore=tests/e2e_pipeline -q` (full suite, with a memory
  watchdog per the plan-036 lesson) — same 13 pre-existing failures, no
  hang, no new failures.

## Out of scope

Single-article `save_article()` behavior (including `_revalidate_cluster`,
noted above as a pre-existing single/bulk asymmetry this plan does not
extend to bulk), dedupe threshold/algorithm changes, schema/index
changes, weakening atomic rollback, admission/validation (plan 034 owns
it — confirmed `save_articles_bulk`'s only real caller,
`BaseCollector._filter_and_save_articles`, already runs `evaluate_admission`
before calling it).
