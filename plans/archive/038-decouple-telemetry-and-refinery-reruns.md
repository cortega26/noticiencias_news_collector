# Plan 038: Decouple telemetry writes and cache Refinery read models

> **Executor instructions**: Optimize measured hot paths without losing run attribution or freshness. Use explicit flush/invalidation semantics. Update plan 038 in `plans/README.md` when complete.
>
> **Drift check (run first)**: `git diff --stat e43bd30..HEAD -- news_collector/observability/enrichment_metrics_store.py news_collector/system/reporter.py news_collector/infrastructure/run_context.py apps/refinery/admin_panel.py tests/unit/test_enrichment_metrics_store.py tests/integration/test_metrics_environment_isolation.py tests/decompose_refinery`

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/033-make-config-refresh-live.md
- **Category**: perf
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Enrichment telemetry serializes every event through one process-wide SQLite connection and commits on each attempt/success/cost call. Separately, Streamlit reruns reconstruct database resources and execute analytics queries even when the analytics tab/data is unchanged. Buffered run-scoped telemetry and explicit cached read models reduce contention and rerun latency while retaining truthful metrics.

## Current state

- `news_collector/observability/enrichment_metrics_store.py:14-48` is a process singleton with one `check_same_thread=False` connection and `RLock`.
- `record_attempt()` at lines 181-301 and `record_success()` at 303-415 update aggregates/history and commit for each event.
- The module creates `enrichment_metrics` at import time around line 647; environment-isolation tests reset private singleton state manually.
- `news_collector/system/reporter.py` reads the global store when generating session reports.
- `apps/refinery/admin_panel.py:2428-2506` constructs `DatabaseManager()` and queries collection, source, score, and category analytics in the top-level rerun path.
- Existing coverage is in `tests/unit/test_enrichment_metrics_store.py` and `tests/integration/test_metrics_environment_isolation.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Metrics tests | `.venv/bin/python -m pytest tests/unit/test_enrichment_metrics_store.py tests/integration/test_metrics_environment_isolation.py -q` | all pass |
| Refinery tests | `.venv/bin/python -m pytest tests/decompose_refinery -q` | all pass |
| Benchmark | `.venv/bin/python scripts/benchmark_metrics.py --events 1000 --max-commits 25` | all events persisted with bounded commits and no loss |
| Full checks | `make lint && make typecheck && make test` | exit 0 |

## Scope

**In scope**: metrics-store lifecycle/injection, run-scoped buffering and flush, atomic aggregate/history writes, environment isolation, reporter integration, Refinery resource/read-model caching and invalidation, tests, and deterministic benchmarks.

**Out of scope**: changing metric definitions, external telemetry vendors, deleting history, realtime dashboards, or caching publication/editorial mutation results.

## Git workflow

- Branch: `advisor/038-telemetry-refinery-performance`.
- Commit example: `perf(observability): batch metrics and cache refinery reads`.

## Steps

### Step 1: Measure current commit and rerun costs

Add deterministic fake-clock/SQLite instrumentation for 1,000 attempt/success events and counters for commits/locks. Extract the analytics query composition from the Streamlit tab into a pure read-model function and measure invocation counts over simulated reruns/tab selection.

**Verify**: baseline tests report current per-event commits and repeated analytics construction without imposing unstable wall-clock thresholds.

### Step 2: Replace the mutable global singleton with injected stores

Make `EnrichmentMetricsStore` accept environment/path/connection lifecycle explicitly. Create it during system bootstrap from a run snapshot and inject it into enrichment/reporting. Retain a narrow compatibility provider only while migrating callers; tests must never mutate `_initialized` or global paths.

**Verify**: two concurrent stores for test/production use distinct files and closing one does not affect the other.

### Step 3: Buffer and flush run-scoped events atomically

Provide a bounded buffer or `record_many()` API. Coalesce aggregate increments/sums/counts per source/strategy while retaining one attributed history row per event. Flush at batch size, run completion, orderly shutdown, and before report generation; rollback the whole flush on failure and retain/retry the buffer according to a documented bounded policy.

**Verify**: 1,000 events produce exact aggregate/history values with at most 25 commits; forced flush failure neither corrupts aggregates nor silently discards buffered events.

### Step 4: Cache only Refinery read models

Use `st.cache_resource` for safe database/read services and `st.cache_data` with a short explicit TTL for analytics read models. Gate expensive analytics loading to the active tab if the Streamlit API permits it. Invalidate after known mutations, config/database path changes, manual refresh, and publication operations. Never cache authorization or mutation responses.

**Verify**: repeated non-mutating reruns reuse the read model; manual refresh and a fixture database mutation cause one fresh query set and updated values.

### Step 5: Expose freshness and failure state

Show analytics `as_of`, environment, and manual refresh; surface stale/failure state without presenting stale data as current. Add flush counters/duration/buffer depth to safe diagnostics.

**Verify**: UI/helper tests cover cache hit, TTL expiry, invalidation, query error, and changed database path; no secret values appear.

## Test plan

- Exact aggregate/history equivalence under batching, concurrency, and retry.
- Environment/path isolation without singleton resets.
- Reporter flush-before-read behavior.
- Refinery read caching, TTL, explicit invalidation, failure, and freshness labels.
- 1,000-event benchmark with commit bound.

## Done criteria

- [ ] Telemetry commits scale with batches, not events.
- [ ] Stores are explicitly constructed and environment-isolated.
- [ ] Reports observe flushed metrics.
- [ ] Refinery analytics queries are cached/invalidation-aware and show freshness.
- [ ] Benchmarks and full backend checks pass.

## STOP conditions

- Stop if buffering can lose events on the supported process termination model; implement synchronous bounded flush first.
- Stop if a cached Streamlit resource is not thread-safe; cache a factory/read model instead.
- Stop if plan 033 changes runtime environment ownership; align with its snapshot lifecycle before migrating the store.

## Maintenance notes

Metric schema changes need batching equivalence tests. Every cached read model needs named invalidation sources and a visible freshness timestamp.

