# Spec: per-run LLM health report (PR-A of the LLM visibility plan)

## Goals
- Every run says how much LLM-dependent work (prescoring, scoring) was really
  done by an LLM vs cache vs heuristics, and why, without opening the log.
- A degraded run (too many heuristic fallbacks, every attempt failed, or every
  provider unavailable) emits `llm.run.degraded` (WARNING) and is flagged in the
  report and in `data/exports/llm_run_report.json`.
- Runs without any LLM activity (CI, no keys) never alert.
- Reporting is fail-open: it can never fail or slow a run.

## Design (see docs/adr/0009-multi-provider-llm-chain.md §15)
- `observability/llm_run_stats.py`: process-wide per-article counters,
  thread-safe, failures logged once; `RunScope` (`begin_scope`/`delta_since`)
  limits a report to one workflow inside a long-lived process.
- `observability/llm_run_report.py`: `build_run_report`, `format_run_report`,
  `write_run_report`, `emit_run_report(scope=...)`; skips count as LLM activity
  (a total outage has 0 calls but is not "no activity").
- `LLMMetricsStore.summary(run_id=..., since_ts=...)`.
- `PreScorer` / `CognitiveScorer` record outcomes. Items an LLM reply omitted are
  scored heuristically (real score, not the zero placeholder), counted as
  `heuristic.incomplete_response` and never cached.
- Config `[llm_health]` (`enabled`, `warn_heuristic_ratio`).
- Wiring: end of `scripts/run_collector.py`; end of `run_publication_pipeline`
  (scoped to that publication).

## Known limits
- Concurrent workflows in the same process share counters.
- A single failed scoring chunk still marks the LLM unhealthy for the rest of
  the cycle (`is_llm_healthy`); the report exposes it (first real run: 307 of
  314 items `llm_unavailable`). Addressed separately.

## Verification
- Unit: aggregation, thresholds, no-activity, outage-as-activity, scope,
  fail-open (store/config/IO), counter-failure logging, PreScorer (4 paths),
  CognitiveScorer (LLM / failed chunk / unavailable / cache / incomplete reply).
- Real: full collection run in a worktree with a DB copy prints the block and
  writes the JSON; degraded alert observed (85 % heuristic in the first run).
- `make lint && make type && make test`, coverage ratchet, `make config-docs-check`.
