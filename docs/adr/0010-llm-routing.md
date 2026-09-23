# ADR-0010: LLM routing — no change; GLM parked, Ultra not wired

**Date**: 2026-09-23
**Status**: Accepted
**Deciders**: Engineering team (operator informed)

---

## Context

The external assessment of 2026-09-21 proposed three routing changes:
keep Super as default, wire Ultra as escalation for hard items, and enter
GLM-5.3-Flash into a text chain. `spec-llm-routing-benchmark.md` turned
that into a pre-registered three-arm benchmark (A control Super, B Ultra,
C GLM) with thresholds fixed **before** the runs.

The benchmark ran its generate phase but could not complete: the hosted
GLM-5.3-Flash endpoint (arm C) was unusable for the whole window (120 s+
probes on 2026-09-21; a 90 s / 0-byte probe on 2026-09-23). C produced zero
ok flows (18 of 40 cases never ran; all 21 recorded rows fell back to local
qwen). The bundle requires ok runs in all three arms, so the cross-critic
matrix, the grounded judge, the blind bundle and the operator ranking could
not run. Numbers live in `reports/evaluation/llm-routing-2026-09.md`.

## Decision

1. **No default change.** `nvidia/nemotron-3-super-120b-a12b` stays the
   default drafting model. Decision 3 of the spec cannot be evidenced
   without the cross-critic matrix.
2. **Ultra is not wired as escalation.** Decision 1 requires a hard-stratum
   cross-critic win-rate ≥ +15 pp that the blocked bundle cannot produce;
   latency (p50 1.88× control) and failure rate were not disqualifying, but
   an unevaluable condition is not a met condition. Revisit on endpoint
   recovery or after a new assessment.
3. **GLM-5.3-Flash is parked until plan 084 (vision).** Decision 2 requires
   ok outputs and human-rank parity that do not exist; the endpoint failure
   itself is recorded as the finding.
4. **License restated** (verified position, 2026-09-21): production serving
   real readers requires NVIDIA AI Enterprise; the local-last Ollama path
   remains the guarantee, and no candidate's trial terms were treated as a
   production license.

## Consequences

- No production config, chain or endpoint changes: arms B/C stay
  harness-only.
- The benchmark branch lands the spec, todo, harness, its regression test,
  the raw runs and this closure. Raw outputs (`runs.jsonl`) are committed as
  evidence.
- Reopening the benchmark means: rerun generate for C, then judge →
  cross-critic → grounded → bundle → operator ranking, then apply §8
  mechanically. The harness is resumable and the decision record above does
  not need to be rewritten unless thresholds are met.
- `spec/llm-routing-benchmark` predates the Wave 2/3 contract mirrors; merge
  it before further harness work.
