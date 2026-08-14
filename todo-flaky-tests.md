# Todo: Fix pre-existing flaky tests (global-state pollution)

## BUG-1: get_config() returns snapshot instead of Config

- [x] `news_collector/config/settings.py` — `get_config()` returns `_CONFIG_STATE` after lazy refresh
- [x] Regression test in `tests/unit/config/test_live_refresh.py` (red first)
- [x] Verify `test_live_refresh` + e2e pair deterministic

## BUG-2: metrics store reads crash on closed connection

- [x] `enrichment_metrics_store.py` — `_ensure_open()` in `get_metrics`/`get_all_metrics`
- [x] Regression test in `tests/unit/test_enrichment_metrics_store.py` (red first)
- [x] Verify session_reporter + s1_refactor + invariants pair

## BUG-3: refresh_runtime_config() overwrites _CONFIG_STATE with non-Config

- [x] `settings.py` — only a real `Config` may become `_CONFIG_STATE`
- [x] Regression test in `tests/unit/config/test_live_refresh.py` (red first)

## Validation

- [x] Seeded full-suite runs: seed 9, 13, 31, 42 → 0 failures each
- [x] `make lint`, `make type`, `make test`
- [x] Commit
