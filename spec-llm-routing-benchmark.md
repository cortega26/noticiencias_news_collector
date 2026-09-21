# Spec — LLM routing benchmark: Super (control) vs Ultra vs GLM-5.3-Flash

Status: proposed. Decides the model-routing question in
`spec-llm-provider-chain.md` follow-ups and the external assessment of
2026-09-21 (Nemotron-3-Super vs Ultra vs GLM-5.3-Flash). No production
behavior changes in this spec — it produces evidence and an ADR.

## 0. Terminology mapping

The external assessment speaks of "F1–F3/audit tasks". This repo has no
F1–F3 labels. The benchmark tasks map to real stages:

| Assessment term | Repo stage(s) | Prompts (config/prompts.yaml) |
|---|---|---|
| Routine drafting / rewriting / extraction | translator, editor, enrichment (`editing` purpose) | translator, editor |
| Headline generation | headlines (`editing` purpose) | headline (+ headline_critic as judge) |
| Editorial audit | editor_critic, headline_critic, auditor | editor_critic, headline_critic |
| Scoring/classification | scoring, prescoring, classifier, council | out of scope (latency-bound; see §6) |

## 1. Goal

Replace opinions (external assessment included) with measured numbers for
three routing decisions:

1. Should Nemotron-3-Super remain the default drafting model?
2. Should Nemotron-3-Ultra be wired as escalation for hard items?
3. Should GLM-5.3-Flash enter any text chain, or wait for plan 084 (vision)?

Output: `reports/evaluation/llm-routing-2026-##.md` + `docs/adr/0010-*.md`
recording the decision — **including an explicit "no change" outcome.**

## 2. Non-goals

- No production config changes (no new `[[llm_endpoints]]` in the live
  chain; candidate credentials live in throwaway env for the harness only).
- No scoring/prescoring/council/classifier changes: those stages are
  latency-bound with measured winners (groq-first; Super+low). Ultra and
  GLM-max-thinking are architecturally incompatible with per-cycle
  deadlines — no benchmark needed to know that.
- No vision evaluation: GLM's image input is benchmarked when plan 084
  (hero alt text) executes, not here.
- No prompt engineering contest: all candidates run the **same pinned
  prompts** (record prompt hashes). Prompt quality is held constant.

## 3. Candidates

| Arm | Model id (verify against provider `/models` before enabling) | Path | Thinking |
|---|---|---|---|
| A — control | `nvidia/nemotron-3-super-120b-a12b` (current `[nvidia].model`) | existing NVIDIA primary | default (off unless purpose body enables) |
| B — escalation | `nvidia/nemotron-3-ultra-550b-a55b` (exact id TBD at run time) | harness-only endpoint entry, same `integrate.api.nvidia.com` base URL | ON (Ultra is a reasoning model; that is the point of the arm) |
| C — challenger | `zai-org/glm-5.3-flash` (exact id TBD at run time) | harness-only endpoint entry | **always-on; pin `extra_body = { reasoning_effort = "low" }` + `clear_thinking = true`** (default is `max` — forgetting this invalidates the cost comparison) |
| D — local reference | `qwen3-next:80b-a3b-instruct-q4_K_M` (current auditor) | existing Ollama | n/a (audit-task reference only, not a drafting candidate) |

**Hard constraint:** arms B and C must NEVER join a live default chain
during the benchmark. The factory puts `[[llm_endpoints]]` into the default
`nvidia → gemini → endpoints → ollama` order, so a careless entry would
silently route production traffic. Harness-only config, separate file,
reviewed diff before any run.

## 4. Dataset

- **40 published articles**, stratified: science / health / technology /
  astronomy+physics, v1 and v2, including a deliberately **hard stratum**
  (~10 items: conflicting sources, preprints, consequential health claims).
  Selection procedure + RNG seed recorded in the report for reproducibility.
- **44 gold enrichment records** at `tests/data/enrichment_eval.jsonl`
  (plan 048 corpus) for the classification/extraction slice.
- Exclusion: retracted or corrected-since items (they would reward
  reproducing known-bad output).

## 5. Tasks per candidate (identical inputs, identical prompts)

1. translate (source → Spanish draft), 2. edit (draft → article body),
   3. headlines (variants), each followed by 4. the matching critic
   (`editor_critic` 7 criteria, `headline_critic`), plus 5. an auditor
   pass over the final body. Record: outputs, critic scores, schema
   validation results, per-call latency, in/out tokens, failures/429s.

## 6. Blind protocol

- Outputs relabeled A/B/C before any human sees them; model metadata
  stripped from the review bundle (the harness already requires honest
  provenance in `baseline.jsonl`/`candidate.jsonl`-style records — keep
  the mapping in a sealed file until scoring closes).
- Human judge (operator): blind Spanish-prose ranking on a 12-article
  subset (stratified, incl. 4 hard). 1–5 voice fidelity
  (`docs/EDITORIAL_VOICE.md`: curious/rigorous/useful), plus pairwise
  preference vs control.
- Automated judges (full set): schema compliance %, critic means,
  auditor finding counts vs sources (hallucination proxy).
- Judge circularity note: the auditor is local qwen (arm D) — it is one
  signal among several, never the sole decider; human rank breaks prose
  ties, critic scores break structure ties.

## 7. Metrics (all reported with distributions, not point estimates)

Schema compliance %, critic mean ± sd per criterion, human mean rank,
hallucination-flag rate, p50/p95 latency per task, mean in/out tokens per
call, failure + 429 rate, quota burn per candidate (via `llm_metrics`
sink + `make llm-report --days`). Free-tier flakes are data: a candidate
that is brilliant but 429s is brilliant-but-unusable — report both.

## 8. Pre-registered decision thresholds

Adopted **before** the runs; the ADR applies them mechanically:

1. **Ultra escalation** iff hard-stratum critic win-rate ≥ +15pp over
   control AND p50 latency < 2× control AND failure rate ≤ control + 2pp.
   Else: no Ultra wiring (revisit in 6 months or on price/limit changes).
2. **GLM text entry** iff Spanish human-rank parity (±0.25 mean rank) AND
   critic within ±3pts AND burn ≤ control. Else: GLM parked until plan 084.
3. **Default change** iff a challenger beats control on critic mean by
   ≥ +5pts with parity-or-better everywhere else. (Prior: unlikely; Super
   is the measured incumbent.)
4. **"No change" is a valid, complete outcome** — recorded in the ADR with
   the numbers, not as a failure.

## 9. Cost, quota, and sequencing guards

- Runs execute sequentially with existing Retry-After/429 handling; any
  tripped free cap aborts that arm's run (recorded as a finding, per §7).
- At ~2 articles/day the full 3-arm benchmark is a few hundred calls —
  no quota anxiety, but record burn anyway (habit for the day volume grows).
- Sequence vs plan 080 Phase 3 (offline replay pilot, currently TODO):
  check its status at execution time. If landed, reuse its harness; if
  not, a standalone replay script under `scripts/` (no Promptfoo, no new
  dependencies — `get_provider` + `prompts.yaml` + existing validators).
  Never build two harnesses.
- Side probe (same window, not part of the main benchmark): Ultra's
  effective hosted context (reported 262k–1M depending on host) — needed
  before any future long-context synthesis design.

## 10. Risks

- Free-tier flakiness contaminating latency comparisons → repeat runs,
  distributions + failure rates first-class (§7).
- Prompt-version drift between arms → pin and record prompt hashes.
- Selection bias in the 40 (cherry-picking easy wins) → stratification +
  seed recorded (§4); hard stratum mandatory.
- License irrelevance fallacy ("free now, decide later") →
  `docs/adr/0010` must restate the verified NIM trial-license position
  (production serving real readers requires AI Enterprise; local-last
  Ollama stays the guarantee) alongside whatever routing wins.
