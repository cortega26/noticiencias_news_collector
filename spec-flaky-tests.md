# Spec: Fix pre-existing flaky tests (order-dependent global-state pollution)

## Goals

The full suite fails intermittently under pytest-randomly shuffling. Three
test groups fail in different random orders; both failures share the same
class: **tests leave process-global state broken, and the next test crashes
on it**. The e2e directory workaround in the Makefile (`--randomly-dont-reorganize`)
papers over the unit→e2e leak instead of fixing it.

Success criteria:

1. `test_live_refresh` + e2e harness pair is deterministic (was: 3/3 fail).
2. `test_session_reporter` + `test_s1_refactor` never crash on the metrics
   store after any other test closes the singleton.
3. Full suite passes across multiple random seeds (seed 9, 13, 31, …) with
   zero failures attributable to global-state pollution.
4. No new abstractions; production bugs fixed in production code, not in tests.

## Root causes (both are real production bugs, exposed by ordering)

### BUG-1: `settings.get_config()` returns the snapshot, not the Config

`news_collector/config/settings.py:401`:

```python
def get_config() -> Any:
    if _CONFIG_STATE is None:
        return refresh_runtime_config()   # returns RuntimeConfigSnapshot
    return _CONFIG_STATE
```

`refresh_runtime_config()` *sets* `_CONFIG_STATE` to the real `Config` but
*returns* the `RuntimeConfigSnapshot` (a dataclass whose `scoring_config` is
a plain dict). So when `_CONFIG_STATE` was reset to `None` (any test that
calls `refresh_runtime_config()` with a partial config and resets globals —
`test_live_refresh` does exactly this), the next `validate_config()` via
`get_config()` receives the snapshot, hits the `scoring_config` dict
fallback, and crashes with `'dict' object has no attribute 'weights'`
(or "missing the 'scoring' section").

**Fix (production):** `get_config()` must return the *Config* it just
refreshed, not the snapshot:

```python
def get_config() -> Any:
    if _CONFIG_STATE is None:
        refresh_runtime_config()
    return _CONFIG_STATE
```

`validate_config()`'s snapshot fallback (`scoring_config` branch) was a
band-aid for this same bug (2026-08-12 comment); it stays as defense-in-depth
but becomes unreachable in the lazy path.

### BUG-2: `EnrichmentMetricsStore.get_metrics`/`get_all_metrics` crash on a closed connection

`news_collector/observability/enrichment_metrics_store.py:701/717`:

```python
def get_metrics(self, source_id): ...
    with self._lock:
        self.flush()          # no-op when buffer empty — never reopens conn
        cur = self.conn.cursor()   # AttributeError when conn is None
```

`flush()` returns early when the buffer is empty **without calling
`_ensure_open()`**, so any read path after `close()` (or after the singleton
was reset by a test) crashes with `'NoneType' object has no attribute
'cursor'`. This is what breaks `test_session_reporter` and
`test_s1_refactor` after `test_continuous_invariants`/`test_adaptive_optimizer`/
`test_strategy_locking` close the singleton (the close-fix in `a7b001a`
exposed it).

**Fix (production):** call `_ensure_open()` before using `self.conn` in
both read methods (same lazy-reopen contract the `cursor` property already
has). `flush()` keeps its early-return semantics.

## Implementation details

### Files

1. `news_collector/config/settings.py` — `get_config()` returns the Config
   (one-line change).
2. `news_collector/observability/enrichment_metrics_store.py` —
   `get_metrics` and `get_all_metrics` call `self._ensure_open()` before
   `self.conn.cursor()`.
3. `tests/unit/config/test_live_refresh.py` — add a regression test:
   after a partial-config refresh + global reset, `get_config()` returns the
   real `Config` (has `.scoring`, not the snapshot).
4. `tests/unit/test_enrichment_metrics_store.py` — add a regression test:
   after `store.close()`, `get_metrics`/`get_all_metrics` reopen and work
   (no AttributeError).

### Explicitly out of scope

- The Makefile e2e-isolation workaround stays (harmless), but no longer
  masks a bug.
- No new fixtures, no test-only "fixes", no new abstractions.

## Verification

1. Deterministic pair: `pytest tests/unit/config/test_live_refresh.py
   tests/e2e_pipeline/test_pipeline_e2e.py -q` → 0 failures.
2. `pytest tests/unit/system/test_session_reporter.py
   tests/unit/system/test_s1_refactor.py
   tests/unit/test_enrichment_metrics_store.py
   tests/integration/test_continuous_invariants.py -q` → 0 failures.
3. Full suite, multiple seeds:
   `pytest tests -q -p randomly --randomly-seed=9`
   `pytest tests -q -p randomly --randomly-seed=13`
   `pytest tests -q -p randomly --randomly-seed=31`
   → 0 failures each (e2e_pipeline included).
4. `make lint`, `make type`, `make test` all green.
5. The two new regression tests fail on the pre-fix code (red) and pass
   after (green).

Change class: storage + config bootstrap boundary → **High**: baseline +
targeted tests + full seeded runs.
