# Todo — LLM routing benchmark (Super vs Ultra vs GLM-Flash)

Follows `spec-llm-routing-benchmark.md`. No production behavior changes
until the ADR lands; arms B/C are harness-only.

Status: **closed 2026-09-23 with "no change"** — the GLM endpoint was
unusable for the whole window (C: 0 ok), so the three-arm comparison could
not run. Report: `reports/evaluation/llm-routing-2026-09.md`; decision:
`docs/adr/0010-llm-routing.md`.

## Setup

- [x] Plan 080 Phase 3 checked (TODO): standalone runner is plan of record
- [x] Candidate model ids verified against NVIDIA `/models`
  (81 models; ultra + glm-flash ids confirmed live)
- [x] Harness-only endpoint config for arms B/C (same NVIDIA base URL;
  GLM pinned low-reasoning; dry-run proves neither joins a live chain)

## Dataset

- [x] 40 stratified cases (seed 20260921) + prompt hash recorded
- [x] Prompt pins: full-file sha256 recorded in dataset manifest
- [ ] Blind bundle assembly (12 items, sealed mapping) after generate — BLOCKED: requires ok in all three arms; C has none

## Runs

- [x] Dataset manifest: 40 seeded cases (19 published-match, 21 backfill,
  11 hard, strata 17/6/12/5) + prompt hash (`scripts/llm_routing_dataset.py`)
- [x] Standalone replay harness with per-arm wiring, mixed-run rule,
  metrics-window attribution (`scripts/llm_routing_replay.py`)
- [x] Full generate runs (40×3, background, resumable) — A/B 40/40 (8 and 18 ok); C 22/40 with 0 ok (dead endpoint)
- [ ] Cross-critic matrix on the bundle subset (post-hoc, no regeneration) — BLOCKED by the bundle condition
- [ ] Grounded fact-check judging over all ok outputs (post-hoc) — not executed (closure)
- [ ] Production-auditor + forced-local judging (post-hoc) — not executed (closure)
- [ ] Side probe: Ultra effective hosted context (262k vs 1M) — not executed

## Analysis + decision

- [x] Compute §7 metrics with distributions (proxies, not tokens) — in the
  report; human blind ranking BLOCKED (no bundle)
- [x] Apply pre-registered §8 thresholds mechanically — not met / not
  evaluable ⇒ no change (ADR-0010)
- [x] Write `reports/evaluation/llm-routing-2026-09.md` with all numbers
- [x] Write `docs/adr/0010-llm-routing.md` (decision + license restatement),
  including "no change" if thresholds are not met
- [x] Ultra-escalation not adopted; revisit on endpoint recovery or a new
  assessment (never the default chain)
- [x] GLM-text not adopted: parked until plan 084 (vision) / endpoint
  recovery
