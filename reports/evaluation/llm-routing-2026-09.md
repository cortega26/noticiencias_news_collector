# LLM routing benchmark — status report (2026-09)

- **Date**: 2026-09-23
- **Spec**: `spec-llm-routing-benchmark.md`
- **ADR**: `docs/adr/0010-llm-routing.md`
- **Raw evidence**: `reports/evaluation/routing/runs.jsonl` (140 rows),
  `judgments.jsonl` (52), `grounded.jsonl` (26)
- **Dataset**: `reports/evaluation/routing_benchmark_cases.jsonl` (40 cases)

## Outcome

**No routing change.** The three-arm protocol could not be completed because
the hosted GLM-5.3-Flash endpoint (arm C) was unusable during the entire
window. GLM is parked until plan 084, and Ultra escalation was not adopted:
its pre-registered threshold requires the three-arm bundle that C's outage
blocked, and an unevaluable condition is not a met condition. "No change" is
a complete outcome under §8.4 of the spec.

## What ran

Dataset: 40 stratified cases (17 ciencia / 6 salud / 12 tecnología / 5
astrofísica), 11 hard, seed 20260921, prompt hash pinned. Dry-run verified
that every arm resolves to its intended primary with zero calls.

Generate (`--phase generate`, resumable, retries up to 3 per case/arm):

| Arm | Model | Cases attempted | Rows | ok / mixed / failed (rows) | Pure-ok cases | schema_ok | wall p50 / p95 |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| A (control) | `nvidia/nemotron-3-super-120b-a12b` | 40/40 | 64 | 8 / 40 / 16 | 8 | 48/64 | 512 s / 1671 s |
| B (escalation) | `nvidia/nemotron-3-ultra-550b-a55b` | 40/40 | 52 | 18 / 22 / 12 | 18 | 40/52 | 962 s / 1867 s |
| C (challenger) | `z-ai/glm-5.3-flash` | 22/40 | 24 | 0 / 21 / 3 | 0 | 21/24 | 1607 s / 2071 s |

- `ok` means every LLM call of the flow was served by the arm's primary
  model; `mixed` means at least one call was served by a fallback. The
  18 cases C never ran are recorded in the raw evidence as missing.
- Arm C's 21 mixed rows were served by the local `qwen3-next:80b` fallback
  (148 calls): GLM itself never completed a flow, so C has zero usable
  outputs for comparison.
- Failure rates (row level): A 25 %, B 23 %, C 12.5 % (of only 24 rows).

## Endpoint evidence (arm C)

- 2026-09-21 (during generate): minimal probes took 120 s+; the harness
  pinned a documented, quality-neutral 60 s timeout so a dead endpoint
  fails fast instead of burning wall-clock before the recorded failover.
- 2026-09-23 (closure probe): a direct `chat/completions` request with
  `reasoning_effort: low` timed out at 90 s with 0 bytes received.

The outage is the finding: a candidate that cannot serve is not a routing
candidate (§7: free-tier flakes are data).

## Local-LLM audit (executed 2026-09-23)

Run after the closure, on the 26 pure-ok outputs (A: 8, B: 18), because the
local reference is cheap and does not need the dead GLM arm.

**Judge** (`--phase judge`; production auditor + forced-local auditor over
every ok output):

| Arm | Judge | Judgments | Result | wall p50 |
| --- | --- | ---: | --- | ---: |
| A | prod | 8 | 8/8 `audit_passed` | 11 s |
| A | forced-local | 8 | 8/8 `audit_passed` | 65 s |
| B | prod | 18 | 18/18 `audit_passed` | 7 s |
| B | forced-local | 18 | 18/18 `audit_passed` | 79 s |

**Grounded fact-check** (`--phase grounded`; claims checked against the
article's own stored source content with the always-Ollama verifier):

| Arm | Runs | Claims | confirmed / uncertain / disputed | Dispute rate |
| --- | ---: | ---: | --- | ---: |
| A | 8 | 36 | 29 / 7 / 0 | 0.0 % |
| B | 18 | 106 | 82 / 24 / 0 | 0.0 % |

Documented deviation: the forced-local auditor inherits the production 45 s
timeout, which the local `qwen3-next:80b` cannot meet (p50 112 s on this
host). The first local pass therefore recorded 26/26 `audit_failed`
(timeout). Re-ran only the local half with
`OLLAMA_TIMEOUT_SECONDS=600` (quality-neutral: a longer timeout can only let
the auditor answer, never bias its verdict); all 26 completed.

Reading: both auditors pass every output and both arms show 0 % grounded
disputes — a ceiling effect, so this evidence discriminates nothing between
A and B. It does fill the "grounded dispute rate ≤ control" condition for
Ultra (0 % ≤ 0 %) and confirms neither arm's claims contradict their sources.

## Remaining blocked phases

| Phase | Status | Reason |
| --- | --- | --- |
| cross-critic matrix (bundle subset) | blocked | Bundle requires ok runs in **all three** arms; C has none |
| blind bundle + operator ranking | blocked | Same |
| §8 threshold application | partial | Cross-critic columns remain unevaluable; latency/failure/grounded conditions are now recorded |
| Ultra hosted-context side probe | not executed | Out of scope for the closure |

## Mechanical application of §8

1. **Ultra escalation** — not met: the hard-stratum cross-critic win-rate
   cannot be computed (bundle blocked). The other three conditions are now
   recorded and neutral-or-better: latency p50 1.88× control (< 2×), failure
   rate not worse, grounded dispute rate 0 % ≤ control 0 %. The decisive
   condition remains unevaluable, so no Ultra wiring.
2. **GLM text entry** — not met: zero ok outputs; endpoint unusable. GLM
   parked until plan 084.
3. **Default change** — not met: no challenger can beat control on the
   cross-critic mean without the matrix. Super stays the default.
4. **No change** — recorded here and in the ADR with the numbers above.

## Reproduction

```bash
PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase dry-run
PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase generate   # resumable
PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase judge      # resumable
OLLAMA_TIMEOUT_SECONDS=600 PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase judge  # local half
PYTHONPATH=. .venv/bin/python scripts/llm_routing_replay.py --phase grounded   # resumable
```

`BENCH_SKIP_ARMS=C` pauses the dead arm without touching recorded rows.
A lost `def main` header (argparse unreachable) was fixed and is guarded by
`tests/scripts/test_llm_routing_replay.py`.

## Follow-ups

- Revisit when the GLM endpoint answers reliably, or when plan 084 (vision)
  runs: rerun generate for C, then cross-critic → bundle → operator ranking
  (judge and grounded are already recorded), and apply §8 mechanically.
- `spec/llm-routing-benchmark` predates the Wave 2/3 contract mirrors; merge
  or rebase it before any further work on the harness.
