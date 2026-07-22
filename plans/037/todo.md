# Plan 037 TODO

## Pre-work (done before writing any refactor code)
- [x] Read `save_articles_bulk` (lines ~539-698), `_assign_cluster`
      (~1048-1177), `articles_exist` (~169-190, the chunked-`IN`
      precedent), `save_article` (~407-538), `_revalidate_cluster`
      (~1191-1236).
- [x] Confirmed `SessionLocal` is `autoflush=False` (`database.py:229`).
- [x] Empirical probe #1: two near-duplicate articles in one
      `save_articles_bulk()` call get DIFFERENT cluster_ids today
      (hamming distance 4, well under threshold 10 — should have
      matched). Root cause: autoflush=False + infrequent flush means
      `_assign_cluster`'s live query can't see the earlier same-batch,
      not-yet-flushed row.
- [x] Empirical probe #2 (the real oracle, per advisor): the SAME two
      payloads through `save_article()` called twice DO join — same
      cluster_id, and both rows end up with `duplication_confidence=0.9375`
      (proving the back-mutation of the matched candidate is real).
      Conclusion: building the in-memory candidate map (Step 4, literally
      as the plan describes it) is the task — it closes a real gap
      between bulk and single-save, not a semantics change to avoid.
- [x] Confirmed `save_articles_bulk`'s only real caller
      (`BaseCollector._filter_and_save_articles`, `base_collector.py:1013`)
      already runs `evaluate_admission()` (line 932) before calling it —
      admission does not need to be re-applied in Step 2.
- [x] Noted (out of scope): `_revalidate_cluster` runs only in
      `save_article`, never in bulk, today — a pre-existing asymmetry not
      mentioned in the plan's Current State/Steps; not extended to bulk.

## Step 1: Characterization fixtures
- [x] `before_cursor_execute`-instrumented SELECT counting
      (`_SelectCounter`) on a real sqlite `DatabaseManager`
      (`tests/unit/storage/test_bulk_persistence_parity.py`).
- [x] Baseline recorded for current (pre-refactor) code: 561 SELECTs for
      100 articles with no in-batch duplicates.
- [x] The load-bearing parity fixture: single-save (2x `save_article()`)
      vs. batch (1x `save_articles_bulk()` with the same 2 near-duplicate
      payloads) — confirmed FAILING against pre-refactor bulk code first
      (different cluster_ids, dup_conf=0.0 both), then made to pass.

## Step 2: Normalize/dedupe input once
- [x] `_prepare_bulk_row()`: validate/canonicalize/normalize/hash/simhash
      exactly once per input, in a private structure.
- [x] `_dedupe_prepared_rows()`: in-batch dedup by canonical URL AND
      content hash, first-occurrence-wins, stable input order (current
      code only deduped URL in-batch — extending to content hash is a
      real, verified gap Step 2 explicitly asks to close; confirmed via a
      test that failed against pre-refactor code first).

## Step 3: Chunked exact-duplicate prefetch
- [x] `_chunked_in_lookup()` (reusing `articles_exist`'s `CHUNK_SIZE=500`
      pattern) for existing canonical URLs and non-null content hashes,
      across the whole prepared/deduped row set, via
      `_filter_existing_articles()`.

## Step 4: Near-duplicate candidate prefetch + in-memory clustering
- [x] Extracted `_resolve_cluster_for_candidates()` (further split into
      `_hamming_filter_hits()`/`_merge_other_clusters()` for ruff C901) as
      pure decision+merge logic shared by both the live single-query path
      (`_assign_cluster`, now a thin wrapper) and the new batched path —
      one implementation, no risk of drift.
- [x] `_fetch_batch_cluster_candidates()`: one prefetch query per bulk
      call across the union of every needed prefix/prefix±1, chunked at
      500, grouped by prefix.
- [x] `_ClusterBatchContext` dataclass: lazy/memoized global fallback
      (augmented with same-batch pending rows), synthetic monotonic
      tie-break id for not-yet-flushed candidates, and
      `resolve()`/`register()` orchestration — extracted to keep
      `save_articles_bulk`'s cyclomatic complexity under the ruff C901
      threshold (mirrors plan 036's `_CycleState` pattern).
- [x] Each newly-added `Article` registered into the in-memory candidate
      map immediately (mutable ORM instance, not a copy) so later
      same-batch rows can join it — closes the Q1/Q2 gap, proven by the
      parity test.
- [x] Cluster-merge propagation to not-yet-flushed same-batch articles
      (the DB-side bulk UPDATE in `_merge_other_clusters` only reaches
      already-persisted rows) — `pending_by_cluster` tracks and updates
      them in place too.

## Step 5: Preserve atomic flush/commit + benchmark
- [x] Existing flush-per-batch_size + final commit + `except: rollback;
      raise` structure preserved untouched (confirmed: unlike the 4
      `return False` methods the plan-036 review fixed, this path already
      re-raises — no PendingRollbackError risk here).
- [x] `scripts/benchmark_bulk_persistence.py`: 100 synthetic articles
      (incl. in-batch exact URL duplicates + near-duplicate clusters),
      reports counts + SELECT totals, asserts bound.

## Verification (all run this session, all green)
- [x] `pytest tests/unit/storage/test_bulk_persistence_parity.py -q` →
      5 passed (near-dup parity oracle, in-batch URL/content-hash dedup,
      existing-DB dedup, SELECT-count scaling: 561 → 4 for 100 articles).
- [x] `pytest tests/integration/test_database.py tests/unit/test_database_race_conditions.py tests/test_database_simhash_behavior.py -q`
      → 20 passed, unchanged.
- [x] `pytest tests/unit/storage/ tests/unit/test_processing_status_constraints.py tests/unit/collectors/ tests/test_database_pending_articles.py -q`
      → 106 passed total (incl. `test_db_chunking.py`, fixed: its 105/100
      test articles all shared identical title+summary, so the new
      in-batch content-hash dedup correctly collapsed them to 1 —
      updated the fixture to unique content per article, matching the
      test's actual intent of verifying flush/commit chunk counts, not
      content-hash behavior).
- [x] `python scripts/benchmark_bulk_persistence.py --articles 100 --max-selects 10`
      → PASS: 99 saved (1 exact-URL dup), 4 SELECTs, ~0.04s.
- [x] `make lint`/targeted mypy → zero new findings vs. baseline (3
      new mypy errors introduced during the refactor were fixed with
      `cast()`, not left).
- [x] `pytest --ignore=tests/e2e_pipeline -q` with memory watchdog (per
      the plan-036 lesson) → 37.71s, 1225 passed, 13 pre-existing
      failures unchanged, 4 skipped, no hang, normal memory.
