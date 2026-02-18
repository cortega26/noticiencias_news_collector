# Pipeline Performance Baselines

The performance regression suite enforces latency thresholds for the offline pipeline
(using the same fixtures we rely on for end-to-end validation). These baselines are
codified in `config/perf_thresholds.py` and exercised by the pytest module in
`tests/perf/test_pipeline_perf.py`.

## When the perf test fails

A failure means one of the measured stages (ingestion, enrichment, or scoring)
exceeded either the configured P95 or max duration. Investigate the perf log produced
at `reports/perf/pipeline_perf_metrics.json` (uploaded in CI as an artifact) to identify
which stage regressed.

## Refreshing baselines after intentional optimizations

When you intentionally optimize part of the pipeline and want to bake the new timing
into the guardrail:

1. Run the profiling helper to capture reference numbers:
   ```bash
   python scripts/profile_pipeline.py > profiling.log
   ```
2. Review the log and identify the steady-state timings for ingestion, enrichment, and
   scoring. Focus on representative runs (`optimized-advanced` scenario is our
   reference).
3. Update the values in `config/perf_thresholds.py` to reflect the new P95/max targets.
   Keep headroom (≈10-15%) to avoid flakiness.
4. Execute the perf test locally to verify it passes:
   ```bash
   pytest tests/perf/test_pipeline_perf.py
   ```
5. Commit the refreshed thresholds together with a summary of the profiling results in
   your PR description.

This workflow ensures we lock in improvements while catching accidental slowdowns.
