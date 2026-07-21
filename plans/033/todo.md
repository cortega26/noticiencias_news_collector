# Plan 033 TODO

## Phase 1: Foundation
- [x] 1.1 Create `RuntimeConfigSnapshot` frozen dataclass in `settings.py`
- [x] 1.2 Create `get_runtime_config()` accessor returning current snapshot
- [x] 1.3 Refactor `refresh_runtime_config()` to build+validate+swap snapshot atomically
- [x] 1.4 Write unit tests for snapshot creation, immutability, versioning, rollback

## Phase 2: Consumer Migration
- [x] 2.1 Migrate `collectors/base_collector.py` (COLLECTION_CONFIG, RATE_LIMITING_CONFIG, ROBOTS_CONFIG, TEXT_PROCESSING_CONFIG)
- [x] 2.2 Migrate `collectors/rss_collector.py` (COLLECTION_CONFIG)
- [x] 2.3 Migrate `collectors/html_collector.py` (COLLECTION_CONFIG)
- [x] 2.4 Migrate `collectors/reddit_collector.py` (COLLECTION_CONFIG)
- [x] 2.5 Migrate `collectors/rate_limit_utils.py` (RATE_LIMITING_CONFIG)
- [x] 2.6 Migrate `scoring/basic_scorer.py` (SCORING_CONFIG, TEXT_PROCESSING_CONFIG)
- [x] 2.7 Migrate `scoring/feature_scorer.py` (SCORING_CONFIG)
- [x] 2.8 Migrate `scoring/__init__.py` (SCORING_CONFIG)
- [x] 2.9 Migrate `scoring/coordinator.py` (ALL_SOURCES stays live in-place; SCORING_CONFIG migrated)
- [x] 2.10 Migrate `storage/database.py` (DATABASE_CONFIG — restart_required; read at construction, engine not hot-rebuilt)
- [x] 2.11 Migrate `storage/article_repository.py` (DEDUP_CONFIG — read per dedup operation, not cached on the repo)
- [x] 2.12 Migrate `storage/source_repository.py` (COLLECTION_CONFIG)
- [x] 2.13 Migrate `infrastructure/requests_client.py` (COLLECTION_CONFIG, RATE_LIMITING_CONFIG — retry decorator replaced with per-call `Retrying(...)` so config isn't baked in at import time)
- [x] 2.14 Migrate `infrastructure/http_client.py` (COLLECTION_CONFIG, RATE_LIMITING_CONFIG — same per-call `AsyncRetrying(...)` fix)
- [x] 2.15 Migrate `enrichment/pipeline.py` (ENRICHMENT_CONFIG)
- [x] 2.16 Migrate `system/__init__.py` (ALL_SOURCES stays live in-place; COLLECTION_CONFIG, SCORING_CONFIG migrated)
- [x] 2.17 Migrate `system/activity_monitor.py` (LOGGING_CONFIG)
- [x] 2.18 Migrate `system/reporting.py` (SCORING_CONFIG)
- [x] 2.19 Migrate `utils/logger.py` (DEBUG, LOGGING_CONFIG — logging setup is one-shot/restart_required by nature; reads live snapshot at that one shot)
- [x] 2.20 Migrate `contracts/collector.py` (TEXT_PROCESSING_CONFIG — module-level constant replaced with a live per-validation read)
- [x] 2.21 Migrate `logic/workflows/pipeline_e2e.py` (ALL_SOURCES stays live in-place; SCORING_CONFIG migrated)

## Phase 3: Refinery Truthfulness
- [x] 3.1 Return applied version and restart_required keys from save_toml_config
- [x] 3.2 Display validation failures instead of claiming success (validate_config now runs before any disk write; failures never persist and are shown via st.error)
- [x] 3.3 Display restart-required notices for operator visibility (render_save_result surfaces restart_required_keys via st.warning)
- [x] 3.4 Verify concurrent reader safety during save (covered by Phase 1's TestConcurrentAccess in tests/unit/config/test_live_refresh.py; save_toml_config's own return contract covered in tests/unit/refinery/test_save_toml_config.py)

## Phase 4: Audit and Cleanup
- [x] 4.1 Run import audit to verify zero mutable by-value imports remain (only intentionally-live ALL_SOURCES remains)
- [x] 4.2 Run `black`/`ruff`/`mypy` on touched files — zero new findings vs. pre-existing baseline
- [x] 4.3 Run `make test` equivalent (`pytest tests --ignore=tests/e2e_pipeline`) — 13 pre-existing failures unchanged, 1149 passed (was 1120), zero new regressions
- [x] 4.4 Update plan status in `plans/README.md`
