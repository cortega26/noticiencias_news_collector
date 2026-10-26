# Pre-registration — GLM-5.3-full (z-ai/glm-5.3) vs Nemotron-3-Super pilot

Date: 2026-10-11. Written BEFORE pilot generate results (canary only).

## Provenance
- Local HEAD: 04016ca8f15dd3db8f59c09fc08451f1799386a6
- origin/main: 2b32e458fac1a15b6138c02d5104b96bb9744fa7 (local 24 behind; working tree dirty with unrelated webhook work — benchmark is read-only, no production change)
- Prompts hash (config/prompts.yaml): 99f394b43f1f2919e3a79932202c4ace9ea114750f2f9f672cd2e62d2583c9e0
- Corpus: reports/evaluation/routing_benchmark_cases.jsonl (40/40 present in data/news_v3.db)
- Pilot: pilot_cases.jsonl (12: astro 2, ciencia 4 [2 hard], salud 3 [1 hard], tecnologia 3 [1 hard]; hard = 1121, 159, 2315, 144)
- Base documents: spec-llm-routing-benchmark.md, docs/adr/0010-llm-routing.md, reports/evaluation/llm-routing-2026-09.md
- Driver: /tmp/glm53_pilot.py (imports scripts/llm_routing_replay.py; Sept evidence in reports/evaluation/routing/ untouched)

## Arms
- A (control): nvidia/nemotron-3-super-120b-a12b, production config untouched.
- C (challenger): z-ai/glm-5.3 (FULL, not Flash) via https://integrate.api.nvidia.com/v1, harness-only endpoint zai-glm-53, timeout 300s, max_tokens 32768, extra_body={"reasoning_effort":"low"}.
- No Ultra arm in this pilot.

## Canary findings (pre-generate, minimal spend: 5 probes)
1. /models lists BOTH z-ai/glm-5.3 and z-ai/glm-5.3-flash (80 models total); Super + Ultra still listed. Prior spec's "zai-org/glm-5.3-flash" prefix was wrong; correct prefix is "z-ai/".
2. Super minimal probe: OK 1.1s, serving_model matches, usage present.
3. Full GLM-5.3 minimal probe: OK 8.0s, serving_model matches, usage present (endpoint ALIVE — contrasts with Flash Sept outage).
4. Full GLM-5.3 with NO extra_body: max-thinking default — reasoning_content only, message.content null, finish=length at 64 tokens. UNUSABLE in pipeline (provider never promotes reasoning_content). Low-reasoning pin REQUIRED (same rationale as Flash spec, not a quality tweak).
5. Full GLM-5.3 with {reasoning_effort:low, clear_thinking:true}: HTTP 400 "Unsupported parameter(s): clear_thinking". With {reasoning_effort:low} only: OK 1.5-3.3s, JSON-compliant, reasoning_tokens 0-9. Super JSON probe also OK.

## Pre-registered deviations from spec-llm-routing-benchmark.md
- D1 (scope): 12-case pilot, not 40. 12-case blind bundle prepared from pilot (bundle shortfall only if fully-ok < 12).
- D2 (arms): 2 arms (A vs C-full), no Ultra; cross-critic matrix is 2x2, not 3x3.
- D3 (GLM params): extra_body low-only, no clear_thinking (endpoint rejects it); timeout 300s not 60s (endpoint healthy).
- D4 (human review): bundle prepared for operator; NO human ranks fabricated — parity conditions stay unevaluable until operator ranks.

## Decision thresholds (spec §8, applied mechanically)
- T1 GLM text entry iff: human-rank parity (±0.25) AND cross-critic within ±3pts AND grounded dispute ≤ control AND burn proxies ≤ control (all under ≥2 fixed critics). Else parked.
- T2 Default change iff: cross-critic mean ≥ +5pts with parity-or-better elsewhere. (Prior: unlikely.)
- T3 No-change/BLOCKED are valid outcomes. With D4, T1/T2 cannot be met in-session → in-session outcome is NO CHANGE pending human review, unless challenger fails outright (then BLOCKED/parked).
- ok/mixed/failed attribution per harness: mixed (any fallback-served call) excluded from quality means, counted in robustness; failures never dropped from denominator.

## Actualizations (2026-10-11, post-run — protocol deviations beyond pre-reg)

- A1 (bundle driver): upstream `cmd_bundle` hardcodes 3 labels (`list("ABC")`)
  and crashes on 2-arm data. `/tmp/glm53_pilot.py` overrides it with an
  otherwise-identical 2-label (`A/B`) implementation (same seed 20260922,
  same N=12/hard=4 rule). Result: 11 items (C-876 never ok).
- A2 (auditor serving): all 46 judgments (prod AND forced-local) record
  `model=qwen3-next:80b…/localhost:11434` — the auditor stage resolves to local
  Ollama on the production path in this repo state. Single-model prose signal;
  ceiling effect (46/46 pass), same as Sept.
- A3 (cross-critic verified genuine): all 44 cross judgments carry real verdict
  dicts (zero fail-open approvals) — matrix reads clean.
- A4 (generate.log covers last 16 flows only): first 14 rows' live logs were
  lost with the aborted buffered invocation; row records are complete (30/30).

## Cost/quota guards
- Sequential runs, existing Retry-After/429 handling; tripped cap aborts arm (recorded as finding).
- Pilot ≈ 12×2 flows × ~5-8 calls ≈ 120-200 calls; usage recorded where available (NVIDIA returns usage; token counts NOT in AttemptRecord per spec §7 — proxies used).
- License: ADR-0010 position restated — production serving real readers requires NVIDIA AI Enterprise; trial terms are not a production license; Ollama local-last stays the guarantee.
