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

## Step 4-5: Refinery caching + freshness UI — DONE (resumed 2026-07-22)

Operator authorized building the missing test infrastructure (engineering
effort, not an operator-secret gap). Followed the precisely-scoped next
slice from spec.md's "Re-examined later the same session" section, in
order:

- [x] Built the `.venv-refinery` test-running convention: `pytest`
      installed unpinned in `bootstrap-refinery` (Makefile), new
      `test-refinery` target, new `tools/ci/pytest_refinery.toml`
      (`testpaths = ["tests_refinery"]` — deliberately outside the main
      `pyproject.toml`'s `testpaths = ["tests"]`, so `make test` never
      tries to collect it).
- [x] Wrote the AppTest characterization test FIRST, confirmed empirically
      (not assumed): `REFINERY_UI_UNSAFE_ALLOW=1` (the app's own existing
      dev/test bypass) clears the auth gate; Streamlit tabs execute their
      body every rerun regardless of visual selection, so Tab 4's real
      metrics are directly assertable; a genuine uncached baseline (DB
      re-queried on every independent rerun) was proven before any caching
      code existed. Caught and fixed a real test-writing bug along the
      way: `mock.patch.object(cls, name, wraps=cls.name)` doesn't bind
      `self` for an unbound method — replaced with a plain function
      wrapper (documented inline in `_call_counter()`).
- [x] Extracted `apps/refinery/analytics_read_model.py`
      (`build_analytics_read_model`) — pure, no `streamlit` import,
      behavior-preserving (same 4 queries, same derivation formulas).
      4 unit tests under the main `.venv`
      (`tests/decompose_refinery/test_analytics_read_model.py`).
- [x] Wired `st.cache_resource` (DB resource) + `st.cache_data(ttl=60)`
      (read model) into `admin_panel.py`'s Tab 4, plus a manual-refresh
      button (`.clear()`) and a freshness caption. Rendering logic
      otherwise untouched.
- [x] Proved caching actually works via the harness, not by inspection:
      cache-hit reuse (2 independent AppTest runs, DB query count stays
      at 1), manual refresh forces a fresh query (via the real button
      click, not a direct `.clear()` call), a query error surfaces
      visibly rather than showing stale data as current. 6 tests total
      in `tests_refinery/`, all green via `make test-refinery`.
- [x] Full main-suite regression (memory-watchdog discipline): 1252
      passed, same 13 pre-existing failures, no new ones. `black`/`ruff`
      clean; `mypy` clean on the new module.

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
- [x] `make test-refinery` → 6/6 passed (Steps 4-5, this pass).
- [x] `pytest tests/decompose_refinery/test_analytics_read_model.py` →
      4/4 passed (Steps 4-5, this pass).
- [x] Full-suite regression re-run after Steps 4-5: 1252 passed, same 13
      pre-existing failures, no new ones.
- [x] `plans/README.md` row for 038 updated PARTIAL → DONE.
