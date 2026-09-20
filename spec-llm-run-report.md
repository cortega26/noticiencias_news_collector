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
- (Fixed in the follow-up below.) A single failed chunk used to mark the LLM
  unhealthy for the whole cycle (first real run: 307 of 314 items unavailable).

## Follow-up: scorer failure cascade and budget
- `CognitiveScorer` disables the LLM only after `max_consecutive_chunk_failures`
  (2) failed chunks in a row; any success resets the streak (also reset per cycle).
- Unavailability reasons are reported separately: `budget_exhausted`,
  `llm_unhealthy`, `breaker_open` (previously all `llm_unavailable`).
- `[scoring] llm_cycle_budget_seconds` (default 600; was a hard-coded 200): the
  first real run scored 371 items (incl. the 14-day re-score) and the 200 s cap
  ended LLM use after ~4 chunks.
- Measured (same DB copy): LLM-scored share 57/371 (15 %) -> 221/370 (60 %) +
  54 cached; residual 26 % = `budget_exhausted` 60 + `chunk_failed` 35.

## Follow-up: re-scoring policy (`[scoring] rescore_uses_llm`)
- Goal: ~80 % of a scoring cycle is re-scoring of completed, unpublished
  articles; it competes with first-time scoring for the free-tier token budget.
- `rescore_uses_llm` (default `false`): re-scores serve cache hits and score the
  rest heuristically (`rescoring.heuristic.no_llm_by_policy`); new articles use
  the LLM as before. The value is read once per cycle (`execute`), never per page.
- `CognitiveScorer.score_batch_async(phase, allow_llm)`: `phase` labels the
  counters (`scoring` | `rescoring`).
- Report: `rescoring` is an informational stage (`ALERTING_STAGES` excludes it: its
  heuristic share is expected and never raises `llm.run.degraded`); it is shown
  even when there is no other LLM activity.
- Verification: `allow_llm=False` serves cache and never calls the LLM;
  coordinator passes phase/flag per source and freezes the flag per cycle; the
  rescoring stage never alerts and renders in rescore-only reports; real run:
  scoring LLM 65/104, rescoring 266 heuristic by policy.

## Verification
- Unit: aggregation, thresholds, no-activity, outage-as-activity, scope,
  fail-open (store/config/IO), counter-failure logging, PreScorer (4 paths),
  CognitiveScorer (LLM / failed chunk / unavailable / cache / incomplete reply).
- Real: full collection run in a worktree with a DB copy prints the block and
  writes the JSON; degraded alert observed (85 % heuristic in the first run).
- `make lint && make type && make test`, coverage ratchet, `make config-docs-check`.
