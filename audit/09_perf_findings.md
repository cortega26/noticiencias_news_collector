# Phase 9 — Performance & Efficiency Findings

## Methodology
- Added JSONL replay fixture (`tests/data/perf/rss_load_sample.jsonl`) with mixed HTTP outcomes (200 + cached 304) to exercise retry, caching, and parallel fetch paths under controlled latency.【F:tests/data/perf/rss_load_sample.jsonl†L1-L4】
- Implemented `src/perf/load_replay.py` harness to patch collectors deterministically for perf tests, enabling reuse across unit tests and the new profiling CLI.【F:src/perf/load_replay.py†L1-L233】
- Created `tools/perf/profile_collectors.py` to sweep sync vs async collectors over arbitrary concurrency levels while collecting throughput/latency summaries (re-usable in CI or local profiling).【F:tools/perf/profile_collectors.py†L1-L147】
- Extended regression suite with targeted assertions for conditional GET/backoff behavior in both sync and async collectors to prevent regressions in transport caching.【F:tests/collectors/test_http_cache_behavior.py†L1-L121】

## Replay metrics (fixture-driven)
| Mode | Duration (ms) | Throughput (items/s) | Speedup vs sync |
| --- | --- | --- | --- |
| Sync baseline | 138.2 | 28.9 | 1.00× |
| Async @1 | 173.6 | 23.0 | 0.80× |
| Async @2 | 81.4 | 49.1 | 1.70× |
| Async @4 | 61.9 | 64.7 | 2.23× |

_Practitioners should avoid `max_concurrent_requests=1` (regression vs sync) and target 4 for ~2.2× speedup on this workload. Profiling CLI prints the full report for additional context._【10210b†L1-L10】

### Latency profile (ASCII chart)
```
Sync  | ██████████████████████████ 138 ms
Async1| ████████████████████████████████ 174 ms
Async2| ████████████ 81 ms
Async4| ████████ 62 ms
```

## Guarded micro-optimizations
- URL canonicalizer now supports configurable LRU caching (`collection.canonicalization_cache_size`) with a default of 2048 entries; collectors configure it from runtime config. Replay benchmark shows ~1.2× speedup on repeated canonicalizations once the cache is warm, keeping the optimization optional (set to `0` to disable).【F:noticiencias/config_schema.py†L224-L230】【F:src/utils/url_canonicalizer.py†L1-L209】【F:src/collectors/rss_collector.py†L1-L120】【F:config.toml†L28-L35】【F:docs/config_fields.md†L27-L35】【F:README.md†L120-L132】【F:tests/test_url_canonicalizer.py†L1-L73】【69b02d†L1-L3】
- Conditional GET + exponential backoff assertions codified for sync/async collectors ensure ETag/Last-Modified metadata is reused and retry jitter stays observable in tests.【F:tests/collectors/test_http_cache_behavior.py†L1-L121】

## Recommendations
1. Use `tools/perf/profile_collectors.py --concurrency` during roll-outs to validate chosen concurrency against fixture-backed baselines before production tuning.【F:tools/perf/profile_collectors.py†L1-L147】
2. Track cache-hit ratio on canonicalization (expose `cache_info()` counters) in future telemetry to quantify real-world gains; disable via `collection.canonicalization_cache_size=0` if sources are mostly unique URLs.【F:tests/test_url_canonicalizer.py†L46-L73】
3. Integrate replay harness into CI perf smoke tests (mark `pytest -m perf`) so regressions in async throughput or caching cause immediate failures.【F:tests/perf/test_async_collector_perf.py†L1-L47】
