# Plan 036: Bound scoring memory, prompts, and concurrency — spec

## Goals

Make one scoring cycle predictable and resumable instead of loading the
entire pending+rescore backlog into memory, building one unbounded LLM
prompt, and scheduling one fallback coroutine per article. Concretely:

1. Explicit, validated workload bounds (page size, max prompt items/chars,
   max fallback concurrency, optional cycle item budget), snapshotted once
   per cycle via `get_runtime_config().scoring_config` (plan 033's pattern).
2. Stable `(collected_date, id)` keyset-cursor pagination for the two
   repository queries the coordinator reads from, added as new page-typed
   methods alongside the existing (unpaged) ones — the existing methods
   have other callers (validation coordinator, `pipeline_e2e.py`, several
   test suites) with different pagination semantics (status-driven, not
   cursor-driven) and are out of scope to change.
3. `ScoringCoordinator.execute()` fetches/adapts/scores/persists one
   bounded page at a time, across both sources, de-duplicating an article
   id that (hypothetically) qualifies for both, and treating a persistence
   failure as cycle failure with the failing page's cursor surfaced in the
   returned diagnostics — never an unconditional `success: True`.
4. `CognitiveScorer` chunks its uncached inputs by item count and estimated
   character size (preserving original order across cache hits and
   generated chunks), and replaces the unbounded `asyncio.gather` fallback
   (in both the coordinator and the scorer itself) with a
   semaphore-bounded pool sized by the same configured worker limit.
5. Workload telemetry (pages, chunks, cache hits, prompt-size estimate,
   max in-flight, duration, committed/failed counts, stop reason) without
   article content, plus `scripts/benchmark_scoring.py` — a deterministic
   1000-item synthetic benchmark asserting the observed peak in-flight
   count never exceeds the configured bound.

## Semantic-dependency check (STOP condition 3) — cleared

Chunking `CognitiveScorer`'s prompts is only safe if one article's score
never depends on which other articles share its prompt. Read
`cognitive_scorer.py:308-407` (`_call_llm_batch` prompt construction and
response parsing) directly to confirm, not assumed:

- The system prompt (`_call_llm_batch`) asks the model to independently
  score *each* numbered item on 4 fixed dimensions (substance, narrative,
  relevance, credibility) — no ranking, no "pick the best N", no
  cross-item comparison instruction anywhere in the prompt text.
- The response is parsed positionally: `res_map = {r.get("item_index", i+1): r
  for i, r in enumerate(res_list)}`, then each item's score is looked up
  by its own `item_index` and computed purely from that item's own
  `scores` dict (`substance*0.35 + narrative*0.30 + relevance*0.20 +
  credibility*0.15`). No item's score reads any other item's fields.

Conclusion: splitting `articles_to_process` into smaller chunks and
issuing one `_call_llm_batch` call per chunk cannot change any individual
article's score — each chunk is scored exactly as if it were the whole
batch, from the model's point of view. Chunking is semantically safe.
Step 4 proceeds.

## Design

### Step 1 — config (`noticiencias/config_schema.py`, `ScoringConfig`)

New fields, all validated (reject zero/negative via `PositiveInt`, reject
excessive via explicit `le`):

- `page_size: PositiveInt = 200` (`le=5000`) — DB page size for scoring
  pagination.
- `max_prompt_items: PositiveInt = 20` (`le=200`) — max articles bundled
  into one `CognitiveScorer` LLM prompt chunk.
- `max_prompt_chars: PositiveInt = 16000` (`ge=1000, le=200000`) —
  estimated max characters per prompt chunk (provider context limits
  cannot be reliably determined without a live model probe — STOP
  condition 1 — so this is a conservative, documented estimate: each
  article's prompt text is capped at ~900 chars by `_call_llm_batch`
  itself, so 16000 chars comfortably fits `max_prompt_items` before the
  char bound ever binds first in practice).
- `cycle_item_budget: Optional[PositiveInt] = None` (`le=1_000_000`) —
  optional cap on total articles processed in one scoring cycle, across
  both sources; `None` (default) means unbounded-by-budget (bounded
  instead by whatever backlog exists, one page at a time).
- `workers` (pre-existing field) gains `le=64` (excessive-value
  guard) and becomes genuinely read — previously the coordinator computed
  `self.config_override.get("scoring_workers") or scoring_config.get("workers", 4)`
  and discarded the result (a dead expression preserved verbatim from an
  earlier extraction, per its own comment). It is now used as the
  configured max fallback concurrency, satisfying Step 4's "using the
  configured worker limit" without introducing a redundant duplicate
  field.

### Step 2 — repository cursors (`news_collector/storage/article_repository.py`)

New frozen dataclasses `ArticleCursor(collected_date, id)` and
`ArticlePage(items, next_cursor)`, plus two new methods:

- `get_pending_articles_page(limit, status=PENDING_STATUS, cursor=None) -> ArticlePage`
- `get_completed_articles_for_rescoring_page(limit, days_back=14, cursor=None) -> ArticlePage`

Both order by `(Article.collected_date, Article.id)` and, when a cursor is
given, filter with the keyset predicate
`(collected_date, id) > (cursor.collected_date, cursor.id)` expressed as
`or_(collected_date > c.collected_date, and_(collected_date == c.collected_date, id > c.id))`
— a plain `collected_date > cursor.collected_date` would skip or repeat
rows that share a timestamp with the cursor row. Both fetch `limit + 1`
rows to determine `next_cursor` without a second COUNT query, trimming to
`limit` before returning.

The existing unpaged `get_pending_articles`/`get_completed_articles_for_rescoring`
methods are untouched — this is additive, per the STOP-condition-driven
decision to keep validation coordinator's status-driven pagination
(`tests/unit/validation/test_validation_coordinator.py`,
`tests/unit/system/test_validation_chunking.py`) and `pipeline_e2e.py`'s
snapshot exports out of scope. No index/migration is required for
correctness: `ORDER BY collected_date, id` executes as a sort today
without a composite index — only *performance* on a very large backlog
would want one, which is noted as a follow-up, not bundled here (per the
plan's own STOP condition 2).

`news_collector/storage/database.py` gets two thin delegating wrappers,
mirroring the existing `get_pending_articles`/`get_completed_articles_for_rescoring`
pass-throughs.

### Step 3 — coordinator page loop (`news_collector/scoring/coordinator.py`)

`execute()` (non-dry-run path) becomes:

1. Snapshot bounds once: `page_size`, `max_prompt_items`, `max_prompt_chars`,
   `max_fallback_concurrency` (`workers`), `cycle_item_budget`,
   `rescore_days` — same override-then-config precedence as today's
   `rescore_days_back` handling.
2. `reset_cycle_metrics()` once per cycle (unchanged — a per-cycle reset,
   not per-page).
3. Iterate sources in order `("pending", "rescore")`; for each, page via
   its `*_page` method until `next_cursor is None` or the empty page
   sentinel, or `cycle_item_budget` is reached (checked before fetching
   the next page, so the last completed page's work is never discarded).
4. A per-cycle `seen_ids: set[int]` guards against an id appearing in both
   sources — filtered out of the *second* occurrence before scoring, so it
   is scored/persisted at most once. (Under current `processing_status`
   values — `validated` for pending, `completed` for rescore — this cannot
   happen today, since the two filters are mutually exclusive; the guard
   makes the coordinator correct-by-construction rather than correct by
   accident of today's status values, and the plan explicitly asks for it.)
5. Each page is adapted to payloads, scored (`score_batch_async` if
   present, else a semaphore-bounded — not unbounded `asyncio.gather` —
   per-article fallback capped at `max_fallback_concurrency`), and
   persisted via one `update_articles_score_bulk()` call for that page
   only. Running stats accumulate across pages.
6. If persistence fails for a page (`update_articles_score_bulk` returns
   `False`), the cycle stops immediately: `success` is `False`, and the
   returned dict carries a `stop_reason: "persistence_failed"` plus a
   `failed_cursor` (the cursor *before* the failed page, so a retry
   resumes at the right place) in `statistics`/top-level diagnostics.
   Everything already committed in prior pages stays committed — only the
   failed page's scores are lost, matching the plan's "surfaced as failure
   with resumable diagnostics", not "the whole cycle silently loses all
   progress".
7. On normal completion (`cycle_item_budget` reached or both sources
   exhausted), `success: True` with `stop_reason` set to `"budget_reached"`
   or `"exhausted"` for observability, plus workload telemetry (pages
   processed, per-source item counts, chunk/fallback stats bubbled up from
   the scorer if it exposes them).

### Step 4 — `CognitiveScorer` prompt chunking + bounded fallback

- `CognitiveScorer.__init__` reads `max_prompt_items`/`max_prompt_chars`
  from its `config` (default `load_config()`), stored as
  `self.max_prompt_items`/`self.max_prompt_chars`.
- `score_batch_async`: after building `articles_to_process` (cache misses,
  unchanged), partition it into chunks that respect *both* bounds — a
  chunk closes when adding the next item would exceed `max_prompt_items`
  or `max_prompt_chars` (estimated as the summed length of each item's
  already-truncated prompt text) — preserving original relative order.
  Call `_call_llm_batch` once per chunk (sequentially — chunks share no
  state, so this is simple and bounded by construction; no separate
  concurrency knob needed here since one LLM call is already a single
  logical unit of work per the existing design). Merge each chunk's
  results back into `results_map` by original index, exactly as today.
- Heuristic fallback path (already per-article, already synchronous/CPU-bound
  — `self.heuristic.calculate_score` has no I/O) is unaffected; the
  *coordinator's* sequential `score_article_async` fallback is what gets
  the semaphore bound (Step 3, item 5), since that is the actual unbounded
  `asyncio.gather` the plan flags at `coordinator.py:111-113`.

### Step 5 — telemetry + benchmark

- `scripts/benchmark_scoring.py`: deterministic fake in-memory repository
  (synthetic `Article`-like rows with distinct `(collected_date, id)`
  pairs, including intentional timestamp ties) and a fake scorer that
  tracks concurrent in-flight calls via a counter guarded by the same
  semaphore-bound contract; runs a 1000-item synthetic backlog through
  `ScoringCoordinator.execute()`, asserts: no single page's payload list
  exceeds `page_size`, observed peak in-flight fallback calls never
  exceeds the configured `max_fallback_concurrency`, and the sum of
  per-page committed counts equals 1000. Exits non-zero (and prints why)
  if any bound is violated — mirroring `scripts/benchmark_metrics.py`'s
  shape from plan 038.

## Verification

- `pytest tests/unit/storage/test_article_repository_pagination.py -q` —
  keyset cursor correctness: equal-timestamp ties, concurrent inserts
  between pages, empty/final page, no id skipped or duplicated across a
  full walk.
- `pytest tests/unit/scoring/test_scoring_coordinator.py -q` — page
  aggregation across multiple pages, persistence-failure-stops-cycle with
  a resumable cursor, cross-source dedup, cycle item budget stop,
  rescore-count bookkeeping preserved across pages, bounded fallback
  concurrency (a fake scorer that records max concurrent in-flight calls).
- `pytest tests/unit/scoring/test_cognitive_scorer.py -q` — chunk
  boundaries by item count and by estimated char size, cache-hit/chunk
  result reassembly in original order, one chunk's timeout/exception
  falling back only for that chunk (other chunks' results preserved), no
  missing/duplicate item across chunks.
- `python scripts/benchmark_scoring.py --articles 1000 --assert-max-inflight 4`
  → exit 0, reports pages/chunks/peak-in-flight within configured bounds.
- `make lint && make type` — no new findings vs. the pre-existing
  baseline (1 lint error in `serving/__main__.py`, 3 mypy errors in
  `contracts/webhook.py` x2 + `collectors/dispatcher.py` x1).
- `pytest --ignore=tests/e2e_pipeline -q` — same 13 pre-existing failures,
  no new failures.

## A real regression found only by running the full suite (not just targeted tests)

Renaming the coordinator's DB calls from `get_pending_articles`/
`get_completed_articles_for_rescoring` to the new paged
`get_pending_articles_page`/`get_completed_articles_for_rescoring_page`
silently broke 3 tests elsewhere in the suite
(`tests/unit/system/test_scoring_isolation.py` x2,
`tests/unit/system/test_d1_pipeline_boundaries.py::test_scoring_boundary_uses_input_model`)
that construct a real `NewsCollectorSystem` and call `_execute_scoring`
against a bare `MagicMock` `db_manager` with only the *old* method names
configured. Because `get_pending_articles_page` was never configured on
those mocks, calling it returned a fresh auto-generated `MagicMock` —
truthy, with a `.next_cursor` that is itself a fresh `MagicMock` (never
`None`) — so `_run_source`'s `while True:` loop never saw an empty page or
a `None` cursor and **looped forever**, each iteration growing
`unittest.mock`'s internal call-tracking structures (`call_args_list`,
etc.) without bound.

This was caught empirically, not by inspection: `tests/unit/` alone ran
clean (38s, normal memory), but the *full* suite (`pytest
--ignore=tests/e2e_pipeline`) climbed to ~97GB RSS on a 125GB machine and
hit a loguru background-writer-thread deadlock partway through, before I
killed it. A `git stash` A/B comparison (baseline clean at 39s; plan-036
changes reproduced the same growth-then-hang at the same ~81% mark)
confirmed the cause was in this plan's changes, not pre-existing
flakiness. Bisecting to `tests/unit/` alone (clean) vs. the full suite
(leaking) narrowed it to files outside `tests/unit/`'s collection, and a
targeted grep for `_execute_scoring`/`get_pending_articles` across the
whole tree found the 3 affected fixtures.

**Resolution**: updated the 3 fixtures to configure
`get_pending_articles_page`/`get_completed_articles_for_rescoring_page`
with real `ArticlePage(items=..., next_cursor=None)` objects instead of
the old flat-list return values — the same shape any correct mock or real
repository implementation must return. Also found and fixed a second,
related issue in the same pass: `test_scoring_isolation.py`'s
`system.scorer = AsyncMock()` fixture made the new
`hasattr(self.scorer, "get_cycle_telemetry")` check in
`_build_result` true for a mock that had never been asked to expose that
method, and calling it returned an unawaited coroutine instead of a dict
(`TypeError: 'coroutine' object is not iterable`) — fixed by explicitly
mocking `get_cycle_telemetry` as sync, exactly mirroring the fixture's
existing (and now clearly justified) precedent for `reset_cycle_metrics`.

**Lesson for future plans**: a coordinator/repository interface rename
needs a full-tree grep for every mock of the old method name, not just
the test files colocated with the changed production code — `tests/unit/`
passing is necessary but not sufficient when the changed code is a
shared, widely-mocked interface boundary. Regression gates for this kind
of change must include a full-suite run before commit, not just the
narrower `pytest tests/unit/scoring` slice.

## Follow-up fixes from the ~20-iteration subagent review

A fresh review subagent independently re-verified this plan's claims
against the actual code (not just spec prose) and found two real issues:

**1. `update_articles_score_bulk`/`update_validation_status_bulk`/
`update_article_score`/`delete_article` could raise instead of returning
`False` on a real persistence failure.** Each method's `except Exception:
return False` handler returned without first calling
`session.rollback()`. Since `ArticleRepository._session()` wraps
`DatabaseManager.get_session()`, whose own contextmanager
unconditionally calls `session.commit()` again on any *normal* exit
(`get_session()`'s `yield session` is followed by `session.commit()`
outside the caller's try/except) — a `return False` after a caught
exception is a normal exit, so that second commit ran against a session
SQLAlchemy had already marked "needs rollback" from the first failed
commit, raising `PendingRollbackError` and silently discarding the
`return False` the caller (here, `ScoringCoordinator._process_page`) was
relying on. This meant Step 3's "persistence failure is surfaced as
failure with resumable diagnostics, never unconditional success" claim
only held in this plan's own tests — which all mock
`update_articles_score_bulk.return_value = False` directly — not against
the real method under a genuine constraint violation. Not part of this
plan's diff (pre-existing, systemic — same pattern in 4 methods), but
directly undermines a claim this plan makes, so fixed here: added
`session.rollback()` before every `return False` in the 4 affected
methods in `article_repository.py`. Verified with a new test
(`tests/unit/storage/test_bulk_persistence_failure_handling.py`) that
first *reproduces* the bug (a bare `return`/no-rollback after a real
`IntegrityError` — a genuine UNIQUE-constraint violation, not a mock —
does leak `PendingRollbackError` out of `get_session()`), then proves the
fix (rollback before return lets `get_session()` exit cleanly).

**2. Chunk-failure cascade wasn't tested past 2 chunks.** `is_llm_healthy`
is a per-cycle flag (reset only by `reset_cycle_metrics()`, once per
cycle), not per-chunk — once any chunk's `_call_llm_batch` returns
falsy, every *later* chunk in the same `score_batch_async` call skips the
LLM entirely (via `_check_budget()`) and goes straight to heuristic, even
though it never itself failed. This flag predates plan 036 (it existed
for the old single-prompt path); chunking just gives one transient
failure a much larger blast radius within a single cycle, since a cycle
can now span many chunks instead of one prompt. This is inherited
behavior, not a bug plan 036 introduced, and changing the circuit-breaker
semantics is out of this plan's scope (out of scope: "changing scoring
formulas/prompts") — but the existing test only used 2 chunks, which
cannot distinguish "isolated to the failing chunk" from "cascades to
everything after it." Added
`test_chunk_failure_cascades_to_later_untried_chunks` (3 chunks) to make
this explicit and characterized rather than silently assumed.

## Out of scope (explicitly, per the plan's own Scope section)

Scoring formulas/prompts' *content*, distributed queues, replacing the
LLM provider, schema migrations (including a composite index for the new
cursor — noted as a performance follow-up, not required for correctness),
and parallelizing database writes.
