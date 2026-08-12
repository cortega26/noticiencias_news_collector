# Plan 045 TODO

## Step 1: Freeze the response and cursor contract
- [x] Pre-existing (11 serving tests: traversal, malformed cursor 400, date boundaries, empty envelope, etc.)

## Step 2: Deterministic query benchmark
- [x] `scripts/benchmark_serving_api.py` — seeded generator (configurable articles/logs/topics, no network), measures p50/p95/min/max, SQL statement count, payload bytes, EXPLAIN fingerprints for unfiltered/source/date/one-topic/multi-topic/deep-cursor
- [x] Same-seed reproducibility (ordering, statement count, plan fingerprints); timing variance reported
- [x] Bulk seeding (`bulk_save_objects`) so 100k datasets seed in seconds
- [x] Baseline captured: `reports/perf/serving_api.json` (10k articles, 3 logs, seed 42)

## Step 3: Budgets from evidence
- [x] `tests/perf/test_serving_api_perf.py` (7 tests): statement count <= 1, payload <= 32KB, contract stable (ordering/keys/cursor)
- [x] Non-timing budgets per plan (no shared-runner microsecond gate)

## Step 4: Optimize the measured dominant path
- [x] Explicit projection in `list_ranked_articles` (13 Article columns + score_log id/explanation) replacing full ORM hydration
- [x] Measured: API p50 225.8ms -> 209.0ms @100k (TestClient, warm); statement count unchanged at 1; payload unchanged
- [x] Window-function latest-log alternative evaluated -> slower (39-46ms vs 18-28ms raw @10k), grouped subquery retained

## Step 5: Index only with plan proof
- [x] Evaluated three candidates at 100k (same-process A/B):
  - DESC cursor index: 418-466ms vs 185-199ms baseline -> 2.3x SLOWER (rejected)
  - ASC (status, collected_date, id): ~201ms -> neutral (rejected)
  - Window-function rewrite: slower (rejected)
- [x] REJECTED by evidence: coalesce() in ORDER BY makes the sort un-indexable; DESC index destroys cache locality at scale
- [x] No migration added (index would have been the only schema change)

## Final gate
- [x] `pytest tests/test_serving_api.py tests/test_database_migrations.py tests/perf/test_serving_api_perf.py` -> 36 passed
- [x] Full suite (excl. e2e_pipeline): 1824 passed
- [x] `make lint` clean
