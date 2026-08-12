# Plan 036: Bound scoring memory, prompts, and concurrency

> **Executor instructions**: Add deterministic paging/chunking without changing article order or score semantics. Verify failure behavior at each chunk boundary. Update plan 036 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/scoring/coordinator.py news_collector/scoring/cognitive_scorer.py news_collector/storage/article_repository.py news_collector/storage/database.py news_collector/config tests/unit/scoring tests/unit/storage`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/033-make-config-refresh-live.md
- **Category**: perf
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

One scoring cycle loads all pending and rescore candidates, constructs all payloads, sends one LLM prompt, and may schedule one coroutine per article. Large backlogs can exhaust memory, exceed model context, or overload the provider. Deterministic pages plus bounded prompt chunks make the workload predictable and resumable.

## Current state

- `news_collector/scoring/coordinator.py:44-59` loads complete pending and completed lists into memory.
- `coordinator.py:72-73` reads `scoring_workers` but discards it; lines 80-92 build and submit one complete payload list.
- `coordinator.py:111-113` creates one fallback task per payload and gathers all concurrently.
- `news_collector/scoring/cognitive_scorer.py:318-352` concatenates every uncached input into one prompt.
- `news_collector/storage/article_repository.py:730-763` supports a pending limit but no stable cursor and rescoring has no limit; ordering is only `collected_date`.
- Existing behavior tests are in `tests/unit/scoring/test_scoring_coordinator.py` and `test_cognitive_scorer.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Scoring tests | `.venv/bin/python -m pytest tests/unit/scoring -q` | all pass, including large-backlog/chunk failures |
| Storage tests | `.venv/bin/python -m pytest tests/unit/storage -q` | stable cursor/page tests pass |
| Full checks | `make lint && make typecheck && make test` | exit 0 |
| Benchmark | `.venv/bin/python scripts/benchmark_scoring.py --articles 1000 --assert-max-inflight 4` | completes with configured bounds and reports peak memory/prompt size |

## Scope

**In scope**: scoring batch/concurrency configuration, stable repository paging for pending/rescore candidates, coordinator processing loop, cognitive prompt chunking, per-chunk persistence/stats, tests, and a deterministic synthetic benchmark.

**Out of scope**: changing scoring formulas/prompts, distributed queues, provider replacement, schema migrations, or parallelizing database writes.

## Git workflow

- Branch: `advisor/036-bounded-scoring`.
- Commit example: `perf(scoring): page and bound scoring workloads`.

## Steps

### Step 1: Define explicit workload limits

Add validated configuration for database page size, maximum items and estimated characters/tokens per LLM chunk, maximum sequential-fallback concurrency, and optional cycle item/time budget. Snapshot these values once per cycle via plan 033. Choose conservative defaults from current provider context limits and record them in active configuration docs.

**Verify**: config tests reject zero/negative/excessive values and coordinator tests prove defaults are applied.

### Step 2: Add stable repository cursors

Extend pending and completed-rescore repository queries with deterministic `(collected_date, id)` ordering and cursor/limit inputs. Return a typed page with next cursor or an equivalent unambiguous contract. Ensure newly updated rows cannot reappear in the same run and equal timestamps cannot skip/duplicate IDs.

**Verify**: storage tests page through fixtures with equal timestamps and concurrent inserts, observing every starting candidate at most once in stable order.

### Step 3: Process and persist one page at a time

Refactor `ScoringCoordinator.execute()` to fetch, adapt, score, aggregate, and bulk-persist a bounded page before fetching the next. De-duplicate an article that qualifies for both candidate sources. Treat persistence failure as cycle failure with the failed cursor in structured diagnostics; do not return unconditional success.

**Verify**: 1,000 synthetic articles never create more than one page of payload objects plus one results page; totals equal the sum of committed chunks.

### Step 4: Chunk model prompts and bound fallback concurrency

In `CognitiveScorer`, partition uncached inputs by item count and estimated input size while preserving original indexes. Merge cached and generated results in input order. Replace unbounded `asyncio.gather` fallback with a semaphore/worker pool using the configured worker limit. A failed chunk may fall back for only that chunk; successful chunks must not be repeated.

**Verify**: tests assert max prompt estimate, max in-flight calls, ordered results across cache hits/chunks, timeout fallback, partial exception, and no missing/duplicate item.

### Step 5: Add workload telemetry and benchmark

Report pages, chunks, cache hits, prompt estimate, max in-flight calls, duration, committed/failed counts, and stop reason without article content. Add `scripts/benchmark_scoring.py` using deterministic fake scorer/repository implementations.

**Verify**: the benchmark command exits 0 at 1,000 items and fails if the observed in-flight count exceeds the configured bound.

## Test plan

- Repository cursor behavior with equal timestamps, inserts, empty/final pages, and source overlap.
- Coordinator page aggregation, per-page commit, failed persistence, budget stop, and rescore counts.
- Cognitive scorer chunk sizes, cache reassembly, concurrency, provider timeout/error, and order preservation.
- Synthetic 1,000-item benchmark records bounded peak work.

## Done criteria

- [ ] No scoring path loads or schedules the entire backlog at once.
- [ ] LLM prompts and fallback concurrency obey validated limits.
- [ ] Stable paging neither skips nor duplicates starting candidates.
- [ ] Persistence failure is surfaced as failure with resumable diagnostics.
- [ ] Full tests and benchmark pass.

## STOP conditions

- Stop if model/provider context limits cannot be determined; implement item/character bounds first and document the uncertainty.
- Stop if stable cursor paging needs a schema index/migration; split that prerequisite into an explicit plan rather than shipping offset paging.
- Stop if score results depend on articles sharing one prompt; document the semantic dependency before chunking.

## Maintenance notes

Review configured bounds when models change. Preserve stable ordering and per-chunk commit semantics in future parallelism work.
