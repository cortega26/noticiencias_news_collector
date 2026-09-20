# TODO: per-run LLM health report

- [x] Stage counters (`llm_run_stats`) + PreScorer/CognitiveScorer instrumentation (#284)
- [x] Report builder/formatter/exporter, `[llm_health]` config, wiring in collector + publication (#284)
- [x] Review fixes: per-workflow scope, outage counts as activity, incomplete replies
      scored heuristically and not cached, counter failures logged (#285)
- [ ] Follow-up: one failed scoring chunk must not disable the LLM for the rest of
      the cycle (treat as N consecutive failures, reset on success)
- [ ] PR-B: prescoring token/latency diet (measure first)
- [ ] PR-C: editorial grounding check (advisory first)
