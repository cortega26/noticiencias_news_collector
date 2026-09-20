# TODO: per-run LLM health report

- [x] Stage counters (`llm_run_stats`) + PreScorer/CognitiveScorer instrumentation (#284)
- [x] Report builder/formatter/exporter, `[llm_health]` config, wiring in collector + publication (#284)
- [x] Review fixes: per-workflow scope, outage counts as activity, incomplete replies
      scored heuristically and not cached, counter failures logged (#285)
- [x] Follow-up: one failed scoring chunk no longer disables the LLM for the cycle
      (2 consecutive failures, reset on success); budget/health/breaker reasons
      reported separately; `[scoring] llm_cycle_budget_seconds` configurable (600)
- [x] Re-scoring skips the LLM by default (`rescore_uses_llm`), reported as its own informational `rescoring` stage
- [x] PR-B: prescoring diet: NVIDIA `reasoning_effort=low` for prescoring only (`[nvidia.purpose_extra_body]`, ADR-0009 §18; benchmark in the ADR)
- [ ] PR-C: editorial grounding check (advisory first)
