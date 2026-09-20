# Spec: LLM canary, time-shift tests and process rules

## Goals
- Detect, with a repeatable *real* bounded run, that the LLM chain does the work
  (free-tier limits, cascades and budget starvation are invisible to fakes).
- Expose tests that depend on "today" by running the suite with the clock moved.
- Codify process rules learned from regressions (docs/AGENTS.md §5.1).

## Design
- `news_collector/observability/llm_canary.py`: pure `evaluate(counts, elapsed,
  thresholds)` over `llm_run_stats` counters (`scoring.llm` vs `scoring.heuristic.*`;
  cache excluded). Pass: LLM ratio >= 0.8 and elapsed <= 120 s.
- `scripts/llm_canary.py` (`make llm-canary`): 20 synthetic articles, built with the
  production adapter (`adapt_to_scoring_input`), scored by `CognitiveScorer` with a
  throw-away cache through the real chain. No remote provider configured -> SKIP
  (exit 0; `--require-keys` -> 2). Verdict failed -> exit 1. Inserts the repo root
  in `sys.path` so it works from a clean `make bootstrap`.
- `make test-timeshift`: `tests/_plugins/time_shift_plugin.py` (time-machine,
  `TIME_SHIFT_DAYS`, default 120). Expiry-gate tests may fail legitimately.

## Verification
- Unit: verdict rules/boundaries, skip and exit codes, distinct synthetic articles,
  adapter keeps content.
- Real: `make llm-canary` -> 20/20 by LLM in ~2 s; +120 days suite: only the 2
  pip-audit allowlist expiry tests fail.
- `make lint && make type && make test`, coverage ratchet.
