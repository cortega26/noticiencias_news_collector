# Plan 038: Decouple telemetry writes and cache Refinery read models — spec

## Outcome: PARTIAL (Steps 1-3 DONE, Steps 4-5 not attempted this pass)

Steps 1-3 (telemetry batching) are fully implemented, tested for exact
correctness equivalence, and wired into the real collection-cycle boundary.
Steps 4-5 (Refinery Streamlit caching) were not attempted — see "Why 4-5
were not attempted" below.

## A correctness landmine found and avoided before writing any code

Before implementing batching, the naive plan was: group buffered events by
source, sum the durations of `success` events, divide by the count of
successes. A pre-implementation review caught that this is **wrong**:
`avg_enrichment_time`/`avg_content_length` divide by
`total_enrichment_attempted` (the *attempt* count), not the success count.
Attempts that never get a matching success (failures) still bump the
divisor. Concrete falsifier, one source:

```
attempt, success(10), attempt, success(20), attempt, attempt, success(30)
```

The original per-event code computes avg = 18.75 (not 20.0, which
`sum(10,20,30)/3` would give). Any "coalesce by source, sum/count"
implementation of batching would have silently shipped a wrong number.

**Resolution**: batching replays every buffered event through the exact
same per-event arithmetic (`_apply_attempt`/`_apply_success`/`_apply_cost`
pure functions in `enrichment_metrics_store.py`), one at a time, in original
per-source order — it defers *when* the DB is written, never *how* the
numbers are computed. `tests/unit/test_enrichment_metrics_store.py::TestBufferedFlushEquivalence`
replays exactly this interleaved sequence through both an immediate
(batch_size=1) and a batched (batch_size=100) store and asserts both
produce avg=18.75, and that every column in the two stores' final rows is
byte-identical.

## Second finding: the real entrypoint never called the "orderly shutdown" hook

The plan's own STOP condition — "stop if buffering can lose events on the
supported process termination model; implement synchronous bounded flush
first" — was checked concretely, not assumed satisfied:

- `System.shutdown()` exists and is called by `pipeline_e2e.py` and the
  smoke/drift scripts, but **`scripts/run_collector.py` (the actual
  Dockerfile `CMD`) never calls it.** Deferring flushes by default and
  relying on that hook would have silently lost buffered events on every
  normal production run, not just crashes.
- `BaseCollector._finalize_collection_cycle`, by contrast, is reached
  unconditionally at the end of every `collect_from_multiple_sources()` /
  `collect_from_multiple_sources_async()` call — the collection layer's own
  boundary, independent of which script invokes it.
- Every writer of `enrichment_metrics` (`enrichment/router.py`,
  `infrastructure/proxy_manager.py`) only ever runs inside a collection
  cycle — confirmed by grep, there is no other call site.

**Resolution**: the default `flush_batch_size` stays `1` (byte-identical to
pre-plan-038 behavior — every `record_*()` call flushes immediately) for
any store that isn't explicitly opted into batching. Real batching is only
ever enabled via `EnrichmentMetricsStore.batched(N)`, a context manager
that raises the batch size on enter and *guarantees* a `flush()` (and reset
to 1) on exit — including on exception. `base_collector.py` wraps both
`collect_from_multiple_sources` methods' bodies in
`enrichment_metrics.batched(40)`. The only loss window under this design is
"at most 39 events, if the process is killed between one auto-flush and the
next, mid-cycle" — a bounded, small exposure equivalent in kind to today's
existing per-event-commit risk (a kill mid-statement already loses at most
one event), just scaled to the batch size instead of 1.

## Step 2: explicit lifecycle, without touching every caller

`EnrichmentMetricsStore()`'s singleton behavior is unchanged (so
`enrichment/router.py`'s 20+ existing call sites, `reporter.py`,
`diagnostics.py` need zero changes) — but:

- `EnrichmentMetricsStore.create_isolated(environment=..., db_path=...,
  flush_batch_size=...)` builds a genuinely separate instance, bypassing
  `__new__`'s singleton cache entirely via `object.__new__`.
- `tests/integration/test_metrics_environment_isolation.py` no longer
  mutates `enrichment_metrics._initialized`/`__init__()` — it uses
  `create_isolated(environment="test")` instead, exactly the "tests must
  never mutate `_initialized` or global paths" requirement.

`ProductionReadonlyStore`/`production_metrics_view` (used by
`StrategyOptimizer`) is untouched — it's a separate, already-simple
read-only class with no singleton/buffer of its own.

## Step 3: buffer, flush, and their failure semantics

- `record_attempt`/`record_success`/`record_failure`/`record_cost` append
  an event dict to `self._buffer` and call `_maybe_flush()` (flush if
  `len(buffer) >= flush_batch_size`).
- `flush()`: groups buffered events by `source_id` (preserving each
  source's own order), seeds each touched source's row from its current DB
  state (or fresh defaults for a never-seen source), replays every event
  through the pure `_apply_*` functions, writes one upsert per touched
  source plus one history row per event (matching exactly which event
  types wrote history rows before — `record_cost` never did, preserved),
  all in one transaction.
- On failure: `conn.rollback()`, re-raise, and the buffer is **not**
  cleared — `del self._buffer[:len(events)]` only runs after a successful
  commit. A caller can retry `flush()` later; nothing is silently dropped.
  Tested directly (`test_forced_flush_failure_neither_corrupts_aggregates_nor_drops_buffer`).
- `get_metrics()`/`get_all_metrics()` call `self.flush()` before reading —
  so any reader going through the *same* store instance (reporter.py,
  diagnostics.py, tests) always sees its own writes, regardless of batch
  state. This is the "Reporter flush-before-read behavior" from the plan's
  Test Plan.

## Verification

- `pytest tests/unit/test_enrichment_metrics_store.py
  tests/integration/test_metrics_environment_isolation.py -q` → 12 passed
  (7 pre-existing + 1 pre-existing isolation-rewrite-safe + 3 new
  equivalence/failure/unit tests + 1 pre-existing optimizer test).
- `python scripts/benchmark_metrics.py --events 1000 --max-commits 25` →
  PASS: 1000 events, immediate=1000 commits (4.4s), batched=25 commits
  (0.19s, ~23x fewer commits and faster), every aggregate row byte-identical
  between the two (excluding the `last_updated` timestamp, which trivially
  differs by wall-clock write time).
- `pytest tests/unit/collectors -q` → 30 passed (confirms the
  `enrichment_metrics.batched()` wiring in `base_collector.py` doesn't
  break collection).
- `pytest --ignore=tests/e2e_pipeline -q` → 1179 passed, 13 pre-existing
  failures unchanged, 4 skipped.
- `make lint` / `make type` → same pre-existing baseline (1 lint, 3 type
  errors), none in any file this plan touched (two new mypy errors this
  plan's own changes introduced — `Cannot determine type of "_initialized"`
  and dict-type inference in the benchmark script — were caught and fixed,
  not left as new baseline noise).

## Why Steps 4-5 were not attempted

Steps 4-5 (cache Refinery/Streamlit read models, expose freshness/failure
state in the UI) touch `apps/refinery/admin_panel.py`, already flagged
elsewhere in `plans/README.md` as a ~2951-LOC "god module" with no
characterization tests. `st.cache_resource`/`st.cache_data` behavior is
meaningfully different inside vs. outside a running Streamlit server
(session state, script-rerun semantics), so verifying cache-hit/TTL/
invalidation behavior credibly needs either a live Streamlit harness or the
same AST-extraction testing technique used for `admin_panel.py` earlier
this session (plan 033) — a nontrivial, separate effort in its own right,
not a natural extension of the telemetry-store work above. Attempting it in
the same pass risked either rushing an unverified UI-caching change into a
already-fragile module, or diluting the rigor applied to Steps 1-3. Per the
same discipline used for plans 021/023/046 (land the safely-verifiable
slice, document the STOP, hand off the rest with full context), this is
recorded as the next slice for whoever picks this back up:

- Extract the analytics query composition
  (`apps/refinery/admin_panel.py:2428-2506`) into a pure, `st`-independent
  read-model function first (this alone is testable without Streamlit).
- Then wrap resource construction in `st.cache_resource` and the read model
  in `st.cache_data(ttl=...)`, gated to the active tab if the Streamlit API
  permits it, invalidated on the mutation/config/db-path-change events the
  plan lists.
- Surface `as_of`/environment/manual-refresh in the UI, plus the new
  `EnrichmentMetricsStore.flush_count` counter this pass added (already
  available for exactly this purpose).
