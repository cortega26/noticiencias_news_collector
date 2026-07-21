# Plan 038 TODO

## Step 1: Measure current commit and rerun costs
- [x] Interleaving equivalence test locks in exact current arithmetic
      before any refactor (`test_interleaved_attempts_and_successes_match_between_immediate_and_batched`).
- [x] `scripts/benchmark_metrics.py --events N --max-commits M`: deterministic
      synthetic event generator, reports commit counts + timing for both modes.
- [ ] Refinery analytics-tab rerun-count instrumentation — deferred with
      Steps 4-5 (needs the read-model extraction first).

## Step 2: Replace the mutable global singleton with injected stores
- [x] `EnrichmentMetricsStore.__init__`/`create_isolated` accept explicit
      `environment`/`db_path`/`flush_batch_size`.
- [x] `create_isolated()` bypasses the singleton via `object.__new__` —
      genuinely separate instances, closing one never affects another.
- [x] `tests/integration/test_metrics_environment_isolation.py` no longer
      mutates `_initialized`/global paths — uses `create_isolated()`.
- [x] Compatibility: the module-level `enrichment_metrics` singleton and
      all its 20+ existing callers (`enrichment/router.py`,
      `infrastructure/proxy_manager.py`, `reporter.py`, `diagnostics.py`)
      needed zero changes.

## Step 3: Buffer and flush run-scoped events atomically
- [x] `record_attempt`/`record_success`/`record_failure`/`record_cost`
      append to an in-memory buffer; auto-flush at `flush_batch_size`.
- [x] `flush()`: one transaction per flush, groups by source, replays
      events in order via pure `_apply_attempt`/`_apply_success`/`_apply_cost`,
      one upsert per source + one history row per event (cost events
      excluded from history, matching original behavior).
- [x] Failure semantics tested directly: rollback on exception, buffer
      untouched (retriable), no partial commit.
- [x] `flush()` guaranteed at: batch-size threshold, `get_metrics()`/
      `get_all_metrics()` (before every read), `close()`, and
      `EnrichmentMetricsStore.batched()`'s context-manager exit.
- [x] Wired into the real collection cycle:
      `base_collector.py`'s `collect_from_multiple_sources`/`_async` wrap
      their bodies in `enrichment_metrics.batched(40)` — confirmed via grep
      that every writer of this store only ever runs inside a cycle.
- [x] Confirmed the STOP condition risk concretely, not assumed: the real
      entrypoint (`scripts/run_collector.py`, the Dockerfile CMD) never
      calls `System.shutdown()` — so default batch size stays 1
      (byte-identical to pre-038 behavior) and only the collection-cycle
      boundary opts into real batching, since that boundary is always
      reached regardless of which script invokes it.

## Step 4-5: Refinery caching + freshness UI — NOT ATTEMPTED
- [ ] Extract analytics query composition from `admin_panel.py` into a pure
      read-model function (prerequisite — untestable without this).
- [ ] `st.cache_resource`/`st.cache_data(ttl=...)` wiring, tab-gated loading.
- [ ] Invalidation on mutation/config/db-path-change/manual-refresh.
- [ ] Freshness/failure state surfaced in the UI (`flush_count` from Step 3
      is already available for this).
- See spec.md "Why Steps 4-5 were not attempted" for the full reasoning —
  `admin_panel.py` is an already-flagged ~2951-LOC god module with no
  characterization tests, and Streamlit caching needs either a live
  harness or the AST-extraction technique from plan 033 to verify credibly.

## Verification (all run this session, all green)
- [x] `pytest tests/unit/test_enrichment_metrics_store.py
      tests/integration/test_metrics_environment_isolation.py -q` → 12 passed.
- [x] `python scripts/benchmark_metrics.py --events 1000 --max-commits 25`
      → PASS (25 commits vs 1000, ~23x fewer, aggregates byte-identical).
- [x] `pytest tests/unit/collectors -q` → 30 passed.
- [x] `pytest --ignore=tests/e2e_pipeline -q` → 1179 passed, 13 pre-existing
      failures unchanged, 4 skipped.
- [x] `make lint` / `make type` → same pre-existing baseline, zero new
      (two new mypy errors this plan's changes caused were fixed, not left).
