# Todo — LLM routing benchmark (Super vs Ultra vs GLM-Flash)

Follows `spec-llm-routing-benchmark.md`. No production behavior changes
until the ADR lands; arms B/C are harness-only.

## Setup

- [ ] Check plan 080 Phase 3 status: reuse its replay harness if landed,
  else scaffold the standalone replay script (`get_provider` +
  `config/prompts.yaml` + existing validators, no new dependencies)
- [ ] Verify candidate model ids against provider `/models` endpoints;
  record exact ids (Ultra + GLM ids are TBD until this step)
- [ ] Build harness-only endpoint config for arms B/C (same NVIDIA base
  URL for Ultra; `extra_body = { reasoning_effort = "low" }` +
  `clear_thinking = true` for GLM). Review the diff to prove neither arm
  can join a live default chain

## Dataset

- [ ] Select 40 stratified articles (science/health/tech/astro+physics,
  v1+v2, ~10 hard) with recorded RNG seed; exclude retracted/corrected
- [ ] Confirm `tests/data/enrichment_eval.jsonl` (44 gold records) current
- [ ] Pin + record prompt hashes for translator/editor/headline/critics

## Runs

- [ ] Run arms A/B/C (+ local reference D for audit tasks) over all tasks;
  record outputs, critic scores, schema results, latency, tokens,
  failures/429s, quota burn
- [ ] Relabel outputs A/B/C, seal the mapping; assemble the blind review
  bundle (12-article stratified subset for human ranking)
- [ ] Side probe: Ultra effective hosted context (262k vs 1M)

## Analysis + decision

- [ ] Compute §7 metrics with distributions; human blind ranking (operator)
- [ ] Apply pre-registered §8 thresholds mechanically
- [ ] Write `reports/evaluation/llm-routing-2026-##.md` with all numbers
- [ ] Write `docs/adr/0010-llm-routing.md` (decision + license restatement),
  including "no change" if thresholds are not met
- [ ] If Ultra-escalation adopted: follow-up plan for the "hard item" flag
  + explicit purpose-chain wiring (never the default chain)
- [ ] If GLM-text adopted: follow-up plan for chain entry with pinned
  low-reasoning body; else confirm GLM parked until plan 084
