# Todo — LLM routing benchmark (Super vs Ultra vs GLM-Flash)

Follows `spec-llm-routing-benchmark.md`. No production behavior changes
until the ADR lands; arms B/C are harness-only.

## Setup

- [x] Plan 080 Phase 3 checked (TODO): standalone runner is plan of record
- [x] Candidate model ids verified against NVIDIA `/models`
  (81 models; ultra + glm-flash ids confirmed live)
- [x] Harness-only endpoint config for arms B/C (same NVIDIA base URL;
  GLM pinned low-reasoning; dry-run proves neither joins a live chain)

## Dataset

- [x] 40 stratified cases (seed 20260921) + prompt hash recorded
- [x] Prompt pins: full-file sha256 recorded in dataset manifest
- [ ] Blind bundle assembly (12 items, sealed mapping) after generate

## Runs

- [x] Dataset manifest: 40 seeded cases (19 published-match, 21 backfill,
  11 hard, strata 17/6/12/5) + prompt hash (`scripts/llm_routing_dataset.py`)
- [x] Standalone replay harness with per-arm wiring, mixed-run rule,
  metrics-window attribution (`scripts/llm_routing_replay.py`)
- [ ] Full generate runs (40×3, background, resumable) — in progress
- [ ] Cross-critic matrix on the bundle subset (post-hoc, no regeneration)
- [ ] Grounded fact-check judging over all ok outputs (post-hoc)
- [ ] Production-auditor + forced-local judging (post-hoc)
- [ ] Side probe: Ultra effective hosted context (262k vs 1M)

## Analysis + decision

- [ ] Compute §7 metrics with distributions (proxies, not tokens); human
  blind ranking (operator) on the 12-item bundle
- [ ] Apply pre-registered §8 thresholds mechanically (cross-critic
  columns, grounded dispute rates, human ranks)
- [ ] Write `reports/evaluation/llm-routing-2026-##.md` with all numbers
- [ ] Write `docs/adr/0010-llm-routing.md` (decision + license restatement),
  including "no change" if thresholds are not met
- [ ] If Ultra-escalation adopted: follow-up plan for the "hard item" flag
  + explicit purpose-chain wiring (never the default chain)
- [ ] If GLM-text adopted: follow-up plan for chain entry with pinned
  low-reasoning body; else confirm GLM parked until plan 084
