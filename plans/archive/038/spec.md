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

## Re-examined later the same session — still correctly PARTIAL

A later pass in this session re-opened Steps 4-5 (033's dependency was
DONE and this looked, at first glance, like unblocked backend-only
work — worth checking rather than assuming still stuck). Two facts were
confirmed empirically, not assumed, that sharpen the handoff above:

- **A real Streamlit test harness (`streamlit.testing.v1.AppTest`) is
  importable** — but only in the separate `.venv-refinery` environment
  (`streamlit==1.53.1` per `requirements-refinery.lock`); the main
  `.venv` that `make test` runs against does not have `streamlit`
  installed at all. `tests/decompose_refinery/test_admin_panel_helpers.py`'s
  own docstring confirms this directly: `admin_panel.py` "cannot be
  imported under the test venv," which is why that suite extracts
  closure-free helper functions via AST + `exec` instead of importing
  the module.
- **There is no existing test-running convention for `.venv-refinery`
  at all** — no pytest config, no `Makefile` target, nothing wired into
  `make test`/`make prepush`. The only existing use of that venv is the
  live `make refinery` target that launches the real Streamlit server.
  `apps/refinery/admin_panel.py`'s Tab 4 (Analytics, lines 2505-2585 as
  of this pass) also sits behind an auth gate
  (`st.session_state["refinery_ui_authenticated"]`, set around line 392)
  that an `AppTest` run would need to satisfy before it could even reach
  the analytics tab.

Conclusion: this is not "a harness exists, so verification is cheap" —
it is "the library is importable, but the test infrastructure,
convention, and auth-bootstrapping to actually exercise `st.cache_*`
behavior in this specific auth-gated, uncharacterized 3042-LOC module
do not exist yet and would need to be built from scratch." Building that
infrastructure plus writing the caching code in the same pass would mean
shipping `st.cache_resource`/`st.cache_data` decorators — whose whole
purpose is to prevent showing stale data as current (Step 5's own
concern) — into a module with zero characterization tests, verified only
by inspection rather than by actually running them. That is a worse
outcome than staying PARTIAL: it would mislabel unmet Step 4/5 Verify
criteria ("repeated non-mutating reruns reuse the read model," "manual
refresh... cause[s] one fresh query set," "UI/helper tests cover cache
hit, TTL expiry, invalidation, query error") as met when they are not
empirically checked. Extracting just the read-model function without the
caching it exists to support was also considered and rejected: absent
the cache wrapping, relocating the same four queries has no standalone
value and either goes unwired (dead code) or gets wired into a tab this
pass still cannot run end-to-end to confirm nothing broke.

**Decision: 038 remains PARTIAL.** Steps 4-5's next slice, more
precisely scoped than the original handoff:
1. Decide and build a real test-running convention for `.venv-refinery`
   first (a `Makefile` target, CI wiring decision) — this is
   infrastructure work in its own right, prior to any caching code.
2. Write an `AppTest`-based test that can satisfy `admin_panel.py`'s
   auth gate and reach Tab 4 at all, as a characterization test *before*
   any caching change (confirm today's uncached behavior first).
3. Only then extract the read-model function and add
   `st.cache_resource`/`st.cache_data`, verified against that harness —
   not by inspection.

## Resumption (2026-07-22): Steps 4-5 completed, harness-first as planned

The operator explicitly authorized building the missing test
infrastructure for this ("build what I can unblock myself" — this is
engineering effort, not an operator-secret gap). Followed exactly the
3-step next slice above, in order, stopping to re-assess after each:

**1. Built the `.venv-refinery` test-running convention.**
`Makefile`'s `bootstrap-refinery` target now also installs `pytest`
(unpinned, same pattern as the main venv's ruff/mypy/black/isort —
outside the hash-pinned `requirements-refinery.lock`). New
`test-refinery` target runs `pytest -c tools/ci/pytest_refinery.toml
--rootdir=.` under `$(PYTHON_REFINERY)` with `REFINERY_UI_UNSAFE_ALLOW=1`
and `NEWS_COLLECTOR_PATH` set. New `tools/ci/pytest_refinery.toml`
(mirrors the existing `pytest_system.toml`/`pytest_contracts.toml`
pattern) scopes `testpaths = ["tests_refinery"]` — a directory
deliberately OUTSIDE the main `pyproject.toml`'s `testpaths = ["tests"]`,
so `make test`/`make test-all` never try to collect it (which would fail
immediately since the main `.venv` has no `streamlit` installed).

**2. Wrote the AppTest characterization test FIRST, before any caching
code existed**, per the plan's own STOP-condition discipline. Confirmed
empirically — not assumed — that:
- `REFINERY_UI_UNSAFE_ALLOW=1` (the app's own existing, documented
  dev/test auth bypass — not a new hack) correctly gets `AppTest` past
  the auth gate.
- Streamlit tabs are a layout construct, not conditional execution —
  every `with tabN:` block's body runs on every script execution
  regardless of which tab is visually "selected," so Tab 4's real
  analytics queries execute and its real metrics
  (`Total Artículos (30d)`, `Score Promedio`, `Fuentes Activas`, ...)
  render and are directly assertable via `at.metric`.
- **Uncached baseline, proven not assumed**: instrumented
  `DatabaseManager.get_collection_stats`/`get_source_performance` with a
  call counter and confirmed a second independent `AppTest` run
  re-queried the database — no caching existed yet, exactly as expected,
  establishing the "before" number the caching change is compared
  against. (This specific test was later superseded once caching landed
  — see `tests_refinery/test_admin_panel_characterization.py`'s own
  module docstring and git history; its role was to unblock proceeding
  to step 3, not to remain a permanent fixture once its job was done.)
- **A real test-writing bug caught along the way**:
  `unittest.mock.patch.object(cls, name, wraps=cls.name)` does NOT bind
  `self` correctly for an unbound method reference (a `MagicMock` is not
  a descriptor) — it raises `missing 1 required positional argument:
  'self'` on every call while still incrementing `call_count`, which
  would have made a naive `spy.call_count >= 1` assertion pass even
  though the real method body never ran and the tab's own
  `except Exception` silently absorbed the failure. Fixed with a plain
  function wrapper (a real descriptor, binds `self` normally) instead of
  a `MagicMock`+`wraps` — this exact gotcha is documented inline in
  `_call_counter()`'s docstring so it isn't rediscovered later.

**3. Extracted the read model and added caching, both verified against
the harness, not by inspection.**
- `apps/refinery/analytics_read_model.py` (new): `build_analytics_read_model(db)`,
  a pure function with zero `streamlit` import — extracted verbatim from
  Tab 4's inline query composition (same 4 queries: `get_collection_stats`,
  `get_source_performance`, `get_score_distribution`,
  `get_category_breakdown`; same derived `avg_score_overall`/`top_sources`
  formulas). Importable and independently unit-tested under the *main*
  `.venv` (`tests/decompose_refinery/test_analytics_read_model.py`, 4
  tests, no Streamlit needed) — this is the behavior-preserving,
  verifiable-without-Streamlit half of the extraction.
- `admin_panel.py`'s Tab 4 block rewritten to call it through two cached
  wrappers: `_get_refinery_analytics_db()` (`st.cache_resource` — safe
  per `DatabaseManager`'s existing `check_same_thread=False`, confirmed
  by reading `database.py` before relying on it) and
  `_load_analytics_read_model(_db)` (`st.cache_data(ttl=60)` — a short
  explicit TTL, per the plan's own Step 4 wording; `_db`
  underscore-prefixed per Streamlit's own convention to exclude the
  unhashable resource from the cache key). A manual refresh button
  (`🔄 Refrescar analítica`) calls `.clear()` on the cached loader
  (Step 4's "Invalidate after ... manual refresh"); a freshness caption
  (`Datos al: <UTC timestamp>`) satisfies Step 5's freshness-display ask.
  Rendering logic (metrics, charts, fallback messages, the outer
  `try/except` boundary) is otherwise untouched — a deliberately
  behavior-preserving edit, not a rewrite.
- **Caching behavior proven via the harness**, not asserted by
  inspection: `test_second_rerun_reuses_cache_and_does_not_requery`
  (two independent `AppTest` "page loads" — DB query count stays at
  exactly 1, proving the cache hit is real); `test_manual_refresh_button_forces_a_fresh_query`
  (clicks the real button via `AppTest`, not a direct `.clear()` call —
  proves the button is actually wired, not just that the API works);
  `test_a_visible_query_error_does_not_show_stale_data_as_current`
  (forces `get_collection_stats` to raise — confirms the existing
  `except Exception -> st.error` path still surfaces visibly rather than
  a stale cached value silently standing in, directly answering Step 5's
  own "must never present stale data as current" concern);
  `test_analytics_freshness_caption_is_shown`. 6 tests total in
  `tests_refinery/`, all passing against the real app via `make
  test-refinery`.
- 4 new tests for the pure read model
  (`tests/decompose_refinery/test_analytics_read_model.py`) run under the
  main `.venv`, no Streamlit needed: total/avg-score derivation, top-5
  sort-and-cap, zero-articles division-by-zero safety, exactly-once
  query-call verification via a fake DB.

**Verification (this pass)**: `make test-refinery` → 6/6 passed.
`.venv/bin/pytest tests/decompose_refinery/test_analytics_read_model.py`
→ 4/4 passed. `black`/`ruff` clean on all touched files; `mypy` clean on
the new `analytics_read_model.py` (apps/ is in mypy's scope, unlike
`scripts/`/`tools/`). Full main-suite regression (memory-watchdog
discipline): 1252 passed, same 13 pre-existing failures as this
session's established baseline, no new failures, 27.32s.

**Plan 038 is now DONE** (all 5 Done Criteria genuinely met): telemetry
commits scale with batches (Steps 1-3, prior pass); stores are
explicitly constructed and environment-isolated (Steps 1-3); reports
observe flushed metrics (Steps 1-3); Refinery analytics queries are
cached/invalidation-aware and show freshness (Steps 4-5, this pass,
harness-verified); benchmarks and full backend checks pass.
