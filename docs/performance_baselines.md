# Performance verification

Status: Active. Repository checked 2026-09-04.

The current retained performance test is `tests/perf/test_serving_api_perf.py`.
It asserts structural budgets (query count, payload size and response
semantics), not wall-clock latency. Timing trends come from
`scripts/benchmark_serving_api.py`. Inspect its dataset, markers and assertions
before using a result to justify an API/query change. Run the test directly so a pytest failure remains visible:

```bash
.venv/bin/python -m pytest tests/perf/test_serving_api_perf.py --no-cov
```

`make perf` selects the `perf` marker and writes JUnit output, but its Make
recipe catches pytest failures and emits a `SKIPPED` artifact. A successful
Make exit therefore does not prove that performance tests passed. Likewise,
verify marker selection and collected test counts rather than assuming a
named target ran every benchmark.

`news_collector/config/perf_thresholds.py` retains historical pipeline budgets.
The earlier pipeline/enrichment/PostgreSQL profile test files cited here are
no longer in the active test tree. Do not present those constants or old
JSON results as current enforced SLOs or production database evidence.

For a proposed optimization, capture a baseline and candidate result using
the same revision-independent dataset and environment. Record hardware,
Python/dependency versions, dataset size, concurrency, warm/cold caches and
whether network/LLM work is real or mocked. Compare error rates and result
quality as well as latency. Change thresholds only with repeatable evidence
and a rationale for tolerances; never relax them merely to obtain a green run.

See `docs/ci.md` for CI coverage and `docs/operations.md` for the distinction
between test artifacts and operational measurements.
