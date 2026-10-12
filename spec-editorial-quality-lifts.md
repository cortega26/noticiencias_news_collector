# Spec — Editorial quality lifts (no model change)

Status: in progress (branch `bench/editorial-quality-lifts`, base `origin/main`).
Motivation: `reports/evaluation/routing-glm53/REPORT.md` (GLM-5.3-full vs
Nemotron-3-Super pilot). The benchmark recommended NO CHANGE of drafting
model and surfaced six model-independent, net-positive lifts plus one process
item. This spec implements all of them with zero production-routing changes.

## Goals / acceptance criteria

1. Every critic-gate decision is recorded per flow, including cache-hit skips
   (today: 0/12 Super run-records carry a verdict; 7/16 logged flows skip
   stage 4 silently).
2. Editor prompt carries an explicit preprint/animal-model limitation cue
   (cross-critic rejects repeatedly demanded exactly this; critic side already
   lists it under rigor).
3. Deterministic voice-tic lint exists as a pure rule module with unit tests
   and advisory wiring (no blocking).
4. Deterministic health guarantee-language check exists, health-scoped via
   `health_scope`, advisory only.
5. Headline-critic exhaustion emits a structured, countable event (today: prose
   warning only). Behavior unchanged (still publishes last headlines).
6. Enrichment stage retries ONCE on total-failure (empty) path before accepting
   empty defaults (today: single attempt; C-876-r2 class failure).
7. Process: quarterly blind-review recommendation recorded (no code).

All lifts are fail-open/advisory except where noted; none blocks publication,
none touches `[[llm_endpoints]]`, chains, or routing.

## Implementation details

### L1 — Critic verdict provenance (`ai_editor.py`, stage-4 caller)

- In the `if cache_s2_6.exists()` branch, set
  `self.last_critic_verdict = {"approved": True, "from_cache": True}` and log
  the cache-hit at info level. Rationale: a checkpoint file means a previous
  run passed the gate; recording that (instead of `None`) makes per-flow
  verdict capture complete for harnesses and the refinery snapshot.
- No change to the gate-run branch. No cache-format change.
- Tests: extend `tests/unit/editorial/` with a cache-hit test asserting the
  recorded verdict carries `from_cache=True` (mock style per
  `test_critic_fail_open_103.py`: `object.__new__(EditorAgent)` + stubbed
  `_get_cache_path`). NOTE: full `process_article` coverage is out of scope;
  target the branch logic via a small seam if needed (keep minimal).

### L2 — Limitations cue (`config/prompts.yaml`, `editor.system`)

- Append to the editor prompt (near "Restricciones Absolutas" / rigor area) a
  concise rule: preprints (bioRxiv/arXiv/medRxiv, non-peer-reviewed) and
  animal-model studies REQUIRE one explicit limitation sentence in the body
  (peer-review status; model organism + human-validation caveat).
- Critic side (`editor_critic` rigor) already lists this — no critic change.
- Verification: `make quality-gate` stays green (prompt change must not break
  snapshot gate); visual diff review of the YAML edit (§5.1.5).

### L3 — Voice-tic lint (`news_collector/editorial/voice_tics.py`, NEW)

- Pure stdlib module (mirror `readability.py`/`health_scope.py` style):
  `check_voice_tics(markdown: str | None) -> list[VoiceTic]` with frozen
  dataclass `{code, message, count, snippets}`.
- Patterns (all observed in benchmark outputs/rejects; lists sourced from the
  existing voice contract + prompts): `imagina` openings, `no es X, es Y`,
  `no solo X sino también Y`, `en un mundo donde`, `sin lugar a dudas`,
  `cabe destacar`, `es importante notar/destacar`, voseo imperatives +
  conjugations (reuse the prompt's explicit lists).
- Hygiene: strip frontmatter; exclude quoted spans (don't flag quoted source
  speech); case-insensitive; report match counts + first snippet.
- Wiring (advisory only, mirror spillover tripwire): `ai_editor` after stage 5
  `logger.warning(f"Voice tics [{tic.code}]: ...")`; `refinery_engine`
  `_enrich_objective_review`-adjacent `run.record_stage("voice_tics", True, …)`
  next to readability (never blocks).
- Tests: `tests/unit/editorial/test_voice_tics.py` — each pattern fires;
  quoted/frontmatter exclusions; empty/None input safe.

### L4 — Health guarantee-language check (`news_collector/editorial/health_claims.py`, NEW)

- Pure module: `find_guarantee_language(body, category) -> list[ finding ]`,
  health-scoped via `health_scope.is_health_scope(...)` (category + keyword
  triggers already owned there — reuse, do not redefine).
- Guarantee patterns: `garantiza(n)?`, `cero riesgo`, `100 % … seguro/eficaz`,
  `todos los pacientes`, `cura definitiva`, `sin efectos secundarios`,
  `previene … (todos|por completo)`. Advisory severity `warn`.
- Same wiring as L3 (ai_editor warning + refinery `record_stage`), never blocks.
- Tests: `tests/unit/editorial/test_health_claims.py` — fires on salud-category
  bodies, silent on non-health, exemptions for quoted text.

### L5 — Headline exhaustion structured event (`ai_editor._generate_headlines_with_critic`)

- In the exhaustion branch, add structured log:
  `logger.warning({"event": "headline_critic.exhausted", "attempts": N,
  "reason": regen_instruction})` alongside the existing prose warning.
  Behavior unchanged (returns last headlines).
- Tests: unit test with stubbed `_generate_headlines` /
  `_headline_critic_pass` asserting the event is logged (caplog or mock
  logger) and last headlines returned.

### L6 — Enrichment single retry (`ai_editor._generate_enrichment_fields`)

- On the total-failure path only (exception → would return
  `_empty_enrichment_fields()`): retry the LLM call + sanitize + validate
  ONCE, then accept empty as today. Skip retry when the enrichment prompt is
  unconfigured (deterministic, retry is pointless).
- Bound: exactly 1 extra attempt, only when first attempt produced nothing
  usable. Log retry at warning level.
- Tests: stub `_send_prompt` to raise once then return valid payload →
  fields returned and 2 calls made; stub to always raise → empty + 2 calls;
  prompt-missing → empty + 0 calls.

### L7 — Process (no code)

- Quarterly blind-review recommendation: reuse
  `reports/evaluation/routing-glm53/blind_bundle.md` protocol on fresh samples.
  Recorded here; no implementation.

## Verification

- New/changed pure rules: focused unit tests (list above), each failing
  without the change (run new tests against a `git stash` of the `news_collector/`
  change if in doubt).
- `make lint && make type && make test` (Medium baseline for editorial rules).
- `make test-boundaries` (ai_editor/refinery orchestration touched — High).
- `make quality-gate` (prompts.yaml + publication-output area touched).
- `make inventory-check` (new top-level `spec-*.md`/`todo-*.md` + new modules);
  `make inventory-refresh` if stale.
- `make docs-check` if any active doc touched (not expected).
- Harness regression `tests/scripts/test_llm_routing_replay.py` passes (no
  harness changes, but verdict-shape change L1 could affect future runs —
  note in PR description).
- PR opened from branch, NOT merged; Codex/Codacy comments read before any
  merge (not in scope — merge explicitly out of scope).

## Risks / non-goals

- No blocking behavior added anywhere (advisory-only rule per repo policy for
  heuristic prose checks; grounding.py precedent).
- No prompt-engineering contest: single concise cue (L2), prompts pinned
  elsewhere unchanged.
- No routing/config/chain changes. No new packages (two narrow modules under
  existing `editorial/`, mirroring `readability.py`).
- L1 changes the shape of `last_critic_verdict` on cache-hit flows
  (`None` → `{"approved": True, "from_cache": True}`): consumers must treat
  `from_cache` as provenance, not a fresh judgment. Refinery snapshot
  requires `average` (absent here) so it stays silent on cached flows —
  documented, unchanged.
