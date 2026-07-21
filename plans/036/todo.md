# Plan 036 TODO

## Pre-work (recon, done before writing any code)
- [x] Read `coordinator.py` (full, 190 lines) and `article_repository.py`
      (lines 700-810) — confirmed plan's "Current state" claims accurate.
- [x] Read `cognitive_scorer.py` prompt construction + response parsing
      (`_call_llm_batch`, lines ~308-407) — confirmed no cross-article
      dependency (per-item parsing by `item_index`, per-item score
      formula) — STOP condition 3 cleared, chunking is safe.
- [x] Read existing `test_scoring_coordinator.py`/`test_cognitive_scorer.py`
      to characterize current behavior before refactoring.
- [x] Confirmed no schema index/migration is required for cursor
      correctness (STOP condition 2 does not trigger) — `ORDER BY
      collected_date, id` runs as a sort without a composite index; only
      perf on huge backlogs would want one (follow-up, not this plan).
- [x] Traced a suspected `config_override` type bug (`SystemConfigOverrideModel`
      instance vs dict reaching `ScoringCoordinator.execute()`'s `.get()`
      calls) — verified empirically it does NOT occur:
      `NewsCollectorSystem.__init__` calls `.model_dump(exclude_none=True)`
      right after validation, so `self.config_override` is always a plain
      dict by the time it reaches the coordinator. No fix needed; false
      alarm caught before writing anything down as fact.

## Step 1: Config bounds
- [x] Added `page_size`, `max_prompt_items`, `max_prompt_chars`,
      `cycle_item_budget` to `ScoringConfig` (`noticiencias/config_schema.py`),
      all rejecting zero/negative (`PositiveInt`) and excessive (`le=...`)
      values.
- [x] Added `le=64` to the pre-existing `workers` field (excessive-value
      guard requested by Step 1's own Verify wording).
- [x] Config test (`tests/unit/config/test_scoring_workload_bounds.py`,
      17 tests): invalid values (0, negative, over the `le` bound) raise
      `ValidationError`; defaults round-trip through `model_dump`; boundary
      values accepted.

## Step 2: Repository cursors
- [x] `ArticleCursor`/`ArticlePage` dataclasses in `article_repository.py`.
- [x] `get_pending_articles_page()` / `get_completed_articles_for_rescoring_page()`
      — keyset `(collected_date, id)` ordering + tuple-comparison
      continuation predicate (`_keyset_predicate`), `limit+1` fetch trick
      for `next_cursor`.
- [x] Delegating wrappers in `database.py`.
- [x] Tests (`tests/unit/storage/test_article_repository_pagination.py`,
      8 tests): equal-timestamp fixtures walked page-by-page see every row
      exactly once in stable order; a naive single-column cursor is proven
      to skip ties (falsifier test); a row inserted between two page
      fetches with an earlier timestamp than the cursor is never seen;
      final/empty page returns `next_cursor=None`; days_back cutoff
      respected for rescore paging.

## Step 3: Coordinator page-at-a-time loop
- [x] Rewrote `execute()`: snapshot bounds once, loop pages per source via
      `_run_source`/`_CycleState`, cross-source `seen_ids` dedup, per-page
      persist via `_process_page`/`_PageResult`, stop-on-persistence-
      failure with resumable cursor in diagnostics (`failed_cursor` = the
      cursor used to fetch the failed page), `cycle_item_budget` stop
      checked before fetching the next page, workload stats accumulated
      across pages. Extracted `_run_source`/`_process_page`/`_accumulate`/
      `_build_result` to keep `execute()`'s cyclomatic complexity under the
      ruff C901 threshold (mirrors plan 038's `_replay_events` extraction).
- [x] Rewrote `test_scoring_coordinator.py` (16 tests, all new
      `ArticlePage`/`ArticleCursor`-based fixtures): dry-run, batch success/
      failure/no-fallback-raises, sequential path, bounded fallback
      concurrency, edge cases (empty/all-excluded/persistence-failure-stops-
      cycle), multi-page aggregation, persistence-failure-mid-cycle keeps
      prior pages committed, cross-source dedup, cycle-item-budget stop,
      rescoring lookback override/defaults.
- [x] Preserved: dry-run path, `new_articles_scored`/`completed_articles_rescored`
      bookkeeping, `average_score`, batch-then-sequential-fallback
      semantics, "no fallback method → raise" semantics — all per-page now
      instead of per-cycle, summed correctly across pages via `_CycleState`.

## Step 4: Cognitive scorer chunking + bounded fallback
- [x] Confirmed (STOP condition 3, before writing any chunking code) that
      `_call_llm_batch`'s prompt has no cross-article ranking/comparison
      instruction and its response is parsed purely per-`item_index` — see
      spec.md's "Semantic-dependency check" section.
- [x] `CognitiveScorer` reads `max_prompt_items`/`max_prompt_chars` from
      config at construction (works with both `config=` and `llm_client=`
      injection paths — fixed a latent gap where `active_config` was only
      computed inside the `llm_client is None` branch).
- [x] `_chunk_articles()`/`_heuristic_fallback()` extracted: chunks
      `articles_to_process` by item-count and estimated-char bounds,
      preserving order; one `_call_llm_batch` call per chunk; merge back
      into `results_map` by original index; a chunk's own total failure
      falls back to heuristic for only that chunk, not the whole batch.
- [x] Coordinator's sequential fallback (`asyncio.gather` over one task per
      payload) replaced with a semaphore of size `max_fallback_concurrency`
      (`_bounded_sequential_score`), reusing the pre-existing (previously
      dead-code) `workers`/`scoring_workers` config slot instead of adding
      a redundant new field.
- [x] Tests (`tests/unit/scoring/test_cognitive_scorer.py`, 10 tests: 5
      pre-existing + 5 new): chunk-size boundaries (item count, char
      estimate), order preservation across cache-hit/chunk boundaries, one
      chunk's total failure falls back only for that chunk (other chunk's
      LLM-derived results untouched), no duplicate/missing item across 10
      articles/4 chunks, bounded concurrency observed via a fake scorer
      tracking max-concurrent in-flight calls (in
      `test_scoring_coordinator.py`).

## Step 5: Telemetry + benchmark
- [x] Workload stats surfaced in `execute()`'s return dict under
      `"telemetry"`: `duration_sec`, `pages_processed`,
      `max_fallback_inflight_observed`, `committed`, `failed`,
      `stop_reason`, plus the scorer's own `get_cycle_telemetry()`
      (`llm_calls`, `chunks_processed`, `cache_hits`, `heuristic_used`,
      `prompt_chars_sent`) merged in when the scorer exposes it — no
      article content anywhere in the telemetry dict.
- [x] `scripts/benchmark_scoring.py`: deterministic fake repository (1000
      synthetic articles incl. timestamp ties every 5th) + fake scorer
      with no `score_batch_async` (forces the bounded-fallback path),
      asserts page size stayed stable across fetches, observed in-flight
      concurrency never exceeds `--assert-max-inflight`, and committed
      count equals the total article count. Exit 0 on success, 1 + reasons
      printed on violation.

## Verification (all run this session, all green)
- [x] `pytest tests/unit/storage/test_article_repository_pagination.py -q`
      → 8 passed.
- [x] `pytest tests/unit/scoring/test_scoring_coordinator.py -q` → 21 passed.
- [x] `pytest tests/unit/scoring/test_cognitive_scorer.py -q` → 10 passed.
- [x] `pytest tests/unit/config/test_scoring_workload_bounds.py -q` → 17 passed.
- [x] `python scripts/benchmark_scoring.py --articles 1000 --assert-max-inflight 4`
      → PASS: 5 pages, committed 1000/1000, max in-flight 4, ~0.35s.
- [x] Targeted mypy/ruff on every touched file → zero new findings.
      `make type`'s real scope (`MYPY_TARGETS` in the Makefile) only covers
      3 files, none touched by this plan, and matches the pre-existing
      3-error baseline exactly when run directly.
- [x] `pytest --ignore=tests/e2e_pipeline -q` (full suite): first run
      exposed a real regression — 3 tests elsewhere in the suite
      (`test_scoring_isolation.py` x2, `test_d1_pipeline_boundaries.py`
      x1) mocked the old unpaged DB methods, so the coordinator's new
      `get_pending_articles_page` returned an unconfigured MagicMock whose
      `.items`/`.next_cursor` were never falsy/None — an infinite loop
      that grew `unittest.mock`'s call-tracking state without bound (saw
      ~97GB RSS before I killed it, mid-run). Confirmed via `git stash`
      A/B (baseline clean at 39s, plan-036 changes reproduced the
      growth+hang) that this was caused by this plan's changes, not
      pre-existing flakiness. Fixed all 3 fixtures to return real
      `ArticlePage` objects; fixed a second related issue
      (`AsyncMock`-based scorer fixture made the new
      `get_cycle_telemetry` hasattr-check return an unawaited coroutine)
      the same way the fixture already handled `reset_cycle_metrics`. See
      spec.md "A real regression found only by running the full suite".
      Re-run after fixes: 38s, 1217 passed, 13 pre-existing failures
      (byte-identical to baseline), 4 skipped, no hang, normal memory.

## Follow-up from ~20-iteration subagent review
- [x] Fixed real bug: `update_articles_score_bulk`/`update_validation_status_bulk`/
      `update_article_score`/`delete_article` could raise `PendingRollbackError`
      instead of returning `False` on a genuine persistence failure (missing
      `session.rollback()` before `return False`, causing `get_session()`'s
      own trailing commit to fail against an already-invalidated session).
      Pre-existing, not part of this plan's diff, but undermined Step 3's
      "persistence failure surfaced as resumable failure" claim under real
      (non-mocked) conditions. Fixed in all 4 sites; proved with a new test
      that reproduces the bug via a real UNIQUE-constraint IntegrityError
      (`tests/unit/storage/test_bulk_persistence_failure_handling.py`).
- [x] Characterized (not changed, out of scope): a chunk failure sets
      `is_llm_healthy=False` for the rest of the cycle, cascading to later
      untried chunks — inherited behavior, existing test only covered 2
      chunks. Added `test_chunk_failure_cascades_to_later_untried_chunks`
      (3 chunks) making this explicit.
- [x] Independently re-verified by the review subagent: no other test
      fixture in the tree mocks `db_manager`/`NewsCollectorSystem` and
      calls `_execute_scoring`/`run_collection_cycle(dry_run=False)`
      without configuring the new paged methods — the 3 fixed in the
      first pass were the only ones.
- [x] Full suite re-run: 40s, 1220 passed, same 13 pre-existing failures,
      no hang, normal memory. Committed as a follow-up.
