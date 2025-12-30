# Collector Benchmark Summary

## Fixtures & Methodology
- Replay workloads using the new fixtures under `perf/fixtures/` to mimic mixed cached/uncached feeds and peak-hour spikes.
- Benchmarks executed via `python tools/perf/profile_collectors.py` with latency instrumentation (avg/p50/p95) and CPU sampling.
- Warm-cache impact measured by running sequential passes against the same in-memory metadata store to expose the content-hash short-circuit.

## Throughput & Latency
| Mode | Concurrency | Duration (ms) | Throughput (items/s) | Speedup vs Sync | Latency p50/p95 (ms) | CPU / IO Wait (s) |
| --- | --- | --- | --- | --- | --- | --- |
| Sync baseline | 1 | 456.6 | 15.3 | 1.00× | 145.0 / 203.5 | 0.008 / 0.448 |
| Async | 1 | 487.9 | 14.3 | 0.94× | 145.0 / 203.5 | 0.038 / 0.450 |
| Async | 2 | 246.2 | 28.4 | 1.85× | 145.0 / 203.5 | 0.008 / 0.238 |
| Async | 4 | 215.5 | 32.5 | 2.12× | 145.0 / 203.5 | 0.009 / 0.207 |
| Async | 8 | 215.9 | 32.4 | 2.11× | 145.0 / 203.5 | 0.009 / 0.207 |

_Source: `tools/perf/profile_collectors.py --fixture perf/fixtures/rss_mixed_latency.jsonl --concurrency 1,2,4,8`【9c50a4†L33-L48】_

## Content-Hash Skip Impact (Warm Cache)
| Collector | Pass | Duration (s) | CPU (s) | Notes |
| --- | --- | --- | --- | --- |
| Sync | Cold | 1.0655 | 0.0118 | First replay processes all articles |
| Sync | Warm | 1.0656 | 0.0118 | Hash skip keeps parity (dominated by IO waits) |
| Async (4 workers) | Cold | 0.3540 | 0.0403 | Initial replay exercises parsing across workers |
| Async (4 workers) | Warm | 0.3245 | 0.0100 | Hash match converts repeated 200s into short-circuit skips |

_Measured via sequential passes on `perf/fixtures/rss_peak_hour.jsonl` reusing metadata between runs.【288402†L1-L8】_

## Profile Excerpt
```
ncalls  tottime  percall  cumtime  percall filename:lineno(function)
  905/14    0.006    0.000    1.821    0.130 <frozen importlib._bootstrap>:1349(_find_and_load)
      2/1    0.000    0.000    0.757    0.757 profile_collectors.py:210(main)
      2/1    0.000    0.000    0.752    0.752 profile_collectors.py:131(profile_collectors)
      2/1    0.000    0.000    0.491    0.491 profile_collectors.py:65(_run_sync)
        3    0.000    0.000    0.453    0.151 rss_collector.py:189(collect_from_source)
        3    0.000    0.000    0.449    0.150 load_replay.py:325(fake_fetch)
        3    0.449    0.150    0.449    0.150 {built-in method time.sleep}
```

_Top cumulative cost centres from `python -m cProfile -s cumtime tools/perf/profile_collectors.py --fixture perf/fixtures/rss_mixed_latency.jsonl --concurrency 4`.【eda5ea†L1-L24】_

