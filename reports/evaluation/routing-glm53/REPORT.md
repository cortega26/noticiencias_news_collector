# GLM-5.3-full (z-ai/glm-5.3) vs Nemotron-3-Super pilot — evaluation report

- **Date**: 2026-10-11
- **Question**: does full `z-ai/glm-5.3` (NVIDIA NIM) provide measurable editorial
  improvements over incumbent `nvidia/nemotron-3-super-120b-a12b`, without
  regressions in Spanish quality, factual reliability, performance, or cost?
- **Base documents**: `spec-llm-routing-benchmark.md`, `docs/adr/0010-llm-routing.md`,
  `reports/evaluation/llm-routing-2026-09.md` (prior: GLM-**Flash** endpoint dead,
  0 ok — this pilot tests the **full** model, a different endpoint).
- **Pre-registration**: `PRE-REGISTRATION.md` (this dir; written before generate).
- **Raw evidence** (this dir): `runs.jsonl` (30 rows), `judgments.jsonl` (46),
  `grounded.jsonl` (23), `cross_critic.jsonl` (44), `blind_bundle.md` (11 items),
  `blind_mapping.sealed.json`, `interim_automated.md`, `generate.log`,
  `judge.log`, `grounded.log`, `cross.log`, `pilot_cases.jsonl`.
- **Driver**: `/tmp/glm53_pilot.py` (imports `scripts/llm_routing_replay.py`
  unmodified; Sept evidence in `reports/evaluation/routing/` untouched).

## Provenance

- Local HEAD `04016ca8`, origin/main `2b32e45` (local 24 behind; tree dirty with
  unrelated webhook work — benchmark is read-only, **zero production changes**;
  `git status` shows only pre-existing modifications).
- Prompts hash `99f394b4…` (`config/prompts.yaml`), identical for both arms.
- Corpus: frozen 40-case set; pilot = 12 stratified cases
  (astro 2, ciencia 4 [2 hard], salud 3 [1 hard], tecnologia 3 [1 hard];
  hard = 1121, 159, 2315, 144). All 40 present in `data/news_v3.db`.
- Harness regression: `tests/scripts/test_llm_routing_replay.py` — **2 passed**.

## Endpoint / identity / auth (canary, 5 probes, pre-generate)

- NVIDIA `/models` (80 entries) lists **both** `z-ai/glm-5.3` and
  `z-ai/glm-5.3-flash` (prior spec's `zai-org/` prefix was wrong; correct is `z-ai/`).
  Super + Ultra still listed.
- Super minimal probe: OK 1.1 s, `serving_model` matches request, usage present.
- Full GLM-5.3 minimal probe: OK 8.0 s, `serving_model=z-ai/glm-5.3`, usage
  present — **endpoint alive** (contrasts with Flash, Sept).
- Full GLM-5.3 with NO `extra_body`: max-thinking default — `message.content`
  null, reasoning in `reasoning_content`, `finish=length` at 64 tokens. The
  provider never promotes `reasoning_content`, so the low-reasoning pin is
  REQUIRED (same rationale as Flash spec, not a quality tweak).
- `clear_thinking:true` → **HTTP 400** `Unsupported parameter(s)` on full-GLM.
  Arm C pins `extra_body={"reasoning_effort":"low"}` only, timeout 300 s.
- JSON-mode probes: both models OK (GLM 1.5 s, 9 reasoning tokens; Super 1.5 s).

## What ran

Generate (resumable, ≤3 attempts per case/arm): 12 cases × 2 arms = 24 keys,
30 rows. **Zero fallback contamination**: every ok row served 100 % by its
arm's primary (`failover-served: 0`, mixed 0). Attribution fingerprints in
each row (`primary_model`/`primary_endpoint` match arm intent; dry-run proved).

| Arm | Keys ok / 12 | Rows ok / failed | schema_ok | wall p50 / p95 | LLM calls (ok flows) | call p50 / p95 | out chars mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A Super (control) | **12/12** | 13 rows (12 ok, 1 failed→retried ok) | 100 % | 338 s / 423 s | 54 | 22.4 s / 61.7 s | 8,625 |
| C GLM-5.3-full | **11/12** | 17 rows (11 ok, 6 failed) | 100 % | 361 s / 586 s | 55 | 16.3 s / 101.9 s | 9,538 |

- Failure modes (all `GeneratedArticleValidationError`, never dropped from
  denominators): in-flow fact-check gate disputes (A-2422 r1: 2014-cilia claim;
  C-2422 r1: MIT-2014 attribution; C-2422 r2: thermal-threshold generalization;
  C-876 r1/r3: "CAC-zero guarantees no events" variants) and V2 enrichment
  incompleteness (C-1771 r1, C-876 r2). Retries recovered 3/4 keys; **C-876
  (statin/CAC stratum salud) failed 3/3** — persistent challenger failure,
  also blocking the 12th bundle item.
- No 429s touched pilot flows (no failover rows); NVIDIA usage (token counts)
  is returned by the API but not persisted in `llm_calls` (schema has no token
  columns) — cost measured via spec-§7 proxies above, as pre-registered.
- Latency parity roughly holds at p50 (C 1.07× A) but C's tail is heavier
  (p95 1.38× A; slowest C flow 586 s vs 423 s).

## Judges

- **Production auditor + forced-local** (`--phase judge`, `OLLAMA_TIMEOUT_SECONDS=600`
  per Sept deviation): 46/46 `audit_passed` (A 12+12, C 11+11). Ceiling effect —
  discriminates nothing (same as Sept). NOTE: all 46 judgments record
  `model=qwen3-next:80b… endpoint=localhost:11434` — the auditor stage resolves
  to local Ollama even on the production path in this repo state, so this is a
  single-model prose signal, not an independent remote audit.
- **Grounded fact-check** (always-Ollama verifier, claims vs stored source
  content): A 56 claims (45 confirmed / 11 uncertain / **0 disputed**),
  C 62 claims (37 confirmed / 25 uncertain / **0 disputed**). Zero post-hoc
  disputes both arms — but C drafts ~20 % more claims per output (5.6 vs 4.7)
  with a 2× higher uncertain rate (40 % vs 20 %).
- **Cross-critic 2×2** (fixed graders, threshold-relevant; all 44 genuine
  verdicts, zero fail-open): approvals —

  | out \ critic | A (Super) | C (GLM) |
  | --- | --- | --- |
  | A outputs | 10/11 | 9/11 |
  | C outputs | 9/11 | 8/11 |

  No diagonal inflation (self ≈ cross). Both fixed critics prefer A outputs by
  exactly 1 case — far below any superiority bar, in either direction.
  Hardest case for both models: 1848 (3/4 rejects); 2315 C-output rejected by
  both critics.

## Per-stage observations

- **Translation/adaptation** (stage 1): no English-leakage or schema failures
  in any ok output either arm (schema_ok 100 %); output length comparable
  (C ≈ +10 % chars).
- **Editorial/technical criticism** (in-flow `editor_critic`, 7 criteria):
  Super's critic returned parseable verdicts on **0/12** A flows (fail-open
  abstain throughout — JSON non-compliance in the critic role); GLM's critic
  returned scored approvals (avg 8.6 example) on **5/11** C flows. Self-graded,
  so not threshold evidence — but a real compliance gap on the control side.
- **Headlines** (logged 16-flow subset): headline-critic final approval C
  10/10 vs A 4/6 (2 reject-final). Self-graded (each arm judged by its own
  model) — signal, not evidence.
- **Structured enrichment**: 100 % schema compliance both arms on ok outputs;
  C-876's 3/3 failure shows the challenger's enrichment+fact-check path is
  brittle on the consequential-health stratum (CAC/statin overgeneralization
  blocked twice by the grounded gate, once by missing fields).
- **Proofreading**: no dedicated proofreading stage exists in the pipeline;
  covered by editor/critic/auditor passes above.

## Blind human review

`blind_bundle.md`: **11 items** (4 hard), labels A/B randomly permuted per item,
mapping sealed in `blind_mapping.sealed.json` (kept out of the bundle). Short
by one: C-876 never produced an ok output. **No human ranks collected
in-session — none fabricated.** Spanish-parity conditions stay unevaluable
until the operator ranks.

## Mechanical threshold application (spec §8, 2-arm pilot)

1. **GLM text entry** — NOT MET (blocked on human review): cross-critic within
   ±3 (✓, −1 under both critics), grounded disputes ≤ control (✓, 0 = 0),
   burn proxies ≤ control (✗/mixed: p95 1.38×, persistent 1-key failure),
   human parity unevaluable (no ranks). → **parked**.
2. **Default change** — NOT MET: requires cross-critic mean ≥ +5 for the
   challenger; observed −1 under both fixed critics. Super stays default.
3. **No-change** — recorded here with the numbers above.
4. Deviations from spec (all pre-registered except the last two, which are
   documented here): 12-case pilot scope; 2 arms (no Ultra → 2×2 matrix);
   C extra_body low-only, timeout 300 s; human ranks pending; bundle driver
   patched for 2 labels (upstream `cmd_bundle` hardcodes 3 and crashes);
   auditor served locally on both judge paths (repo state, not a run choice).

## Costs / quotas / license

- Pilot spend ≈ 30 flows × ~5 calls ≈ 160 LLM calls (54+55 on ok flows),
  all sequential with existing Retry-After/429 handling; no cap tripped on
  pilot flows; no paid usage enabled; keys stayed in `.env` (git-ignored).
- Token counts unavailable in harness records (by schema design); proxies
  above + canary usage samples retained in `PRE-REGISTRATION.md`.
- License (ADR-0010 restated): production serving real readers requires NVIDIA
  AI Enterprise; trial terms are not a production license; local-last Ollama
  stays the guarantee. Nothing in this pilot authorizes production routing.

## Recommendation

**NO CHANGE — keep `nvidia/nemotron-3-super-120b-a12b` as the default drafting
model; do not wire full GLM-5.3 into any text chain.** Evidence: (a) cross-critic
dead heat with a −1 lean to control under both fixed graders (needs +5);
(b) challenger key-failure 1/12 vs control 0/12, concentrated in
consequential-health content; (c) heavier latency tail; (d) human Spanish-parity
still unevaluable. "GLM for criticism only" is not supported either: GLM-as-critic
approved A-outputs 9/11 vs Super-as-critic 10/11 — no critic-quality edge
demonstrated (its one edge is critic-JSON compliance, not judgment quality).

Reopen path (no ADR rewrite needed unless thresholds met): collect operator
ranks on the sealed 11-item bundle; optionally extend to the frozen 40 with the
same driver; then apply §8 mechanically. The harness is resumable and September
evidence is untouched.

## Reproduction

```bash
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase dry-run
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase generate   # resumable ≤3 attempts
OLLAMA_TIMEOUT_SECONDS=600 PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase judge
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase grounded
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase cross-critic
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase bundle
PYTHONPATH=. .venv/bin/python /tmp/glm53_pilot.py --phase analyze
```
