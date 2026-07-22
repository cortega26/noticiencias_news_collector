# Spec: Plan 048 — Spike a curated multilingual topic and entity registry

## Goals

Per `plans/048-spike-curated-enrichment-registry.md` (the authoritative
plan file — this document only tracks this plan's own execution, not a
restatement of its content):

- Step 1: produce the editorial ontology/consumer map
  (`docs/spikes/curated-enrichment-registry.md`).
- Steps 2-6: build the evaluation corpus, baseline, candidate registry,
  comparison, and adoption ADR — **gated by the plan's own STOP
  condition**: "Stop at corpus/guidelines if there is no qualified
  editorial reviewer or safe representative data."

## Why this plan stops after Step 1

This is running as an unattended autonomous session. Step 2 explicitly
requires "two reviewers [to] independently label a statistically useful
subset" and adjudicate disagreements — that is a real human-judgment
requirement, not a data-generation task an agent can substitute for
without producing fabricated governance (labels dressed as independently
reviewed when they are not). Step 3's baseline is only evidentially
meaningful once Step 2's corpus exists (the plan itself disqualifies the
6 existing golden examples as sufficient evidence). Steps 4-6 depend on
2-3's outputs. See `docs/adr/0004-curated-enrichment-registry-spike.md`
for the full decision record.

## Implementation details (what was actually done)

1. Recon: read `config.toml`'s `pattern_v1` block, `config_schema.py`'s
   `TopicConfig`/`EntityPattern`/`EntityPatterns`/`ModelConfig`,
   `settings.py`'s `_normalize_enrichment`, `ConfigurableNLPStack`
   (`nlp_stack.py`) end to end, every real consumer of `enrichment.topics`/
   `enrichment.entities` (feature scoring, reranker, serving API, image
   briefs — confirmed `CognitiveScorer` and monitoring/observability are
   NOT content consumers, contrary to the plan's broader "monitoring"
   framing, which turns out to mean pipeline-health metrics, not
   topic/entity content), `tests/data/golden_articles.json`, and
   `tests/test_enrichment_pipeline.py`. All findings are file:line cited
   in `docs/spikes/curated-enrichment-registry.md`.
2. Wrote `docs/spikes/curated-enrichment-registry.md` (Step 1's literal
   Verify target): five-way label vocabulary (editorial category / broad
   topic / named entity / synonym-alias / trend term) mapped onto the two
   real structures (`TopicConfig`, `EntityPatterns`); full consumer table
   with file:line; stable-ID/deprecation-link/cross-language-equivalence
   gaps documented as proposed vocabulary (not implemented); allowed
   entity labels with examples/non-examples per language; ambiguity rules
   (only one exists today: `case_sensitive` on the `TECH`/"IA" entry);
   multi-topic semantics (5-cap, declaration-order, `topics[0]` privileged
   by image briefs); what `general` means (residual fallback, not a real
   topic); golden-example coverage summary.
3. Wrote `docs/adr/0004-curated-enrichment-registry-spike.md`: STOP
   decision at Step 2, with explicit alternatives considered (fabricating
   a synthetic-but-labeled-as-reviewed corpus was rejected as producing
   fabricated governance, not caution) and concrete next steps for
   whoever resumes with a real reviewer and corpus.
4. Did NOT build `scripts/evaluate_enrichment_registry.py` (Step 3) — a
   deliberate scope decision, not an oversight: the plan's own Step 3
   Verify criterion disqualifies the 6 existing golden examples as
   sufficient evaluation evidence, so an evaluator that could only ever
   run against them would produce a number with no real evidential value
   for the adoption decision Steps 4-6 require.
5. No production code, `config.toml`, or `config_schema.py` changes —
   Done Criterion "Production model/configuration remains unchanged
   during the spike" holds trivially (nothing touched).

## Verification

- [x] `docs/spikes/curated-enrichment-registry.md` exists and satisfies
      Step 1's own Verify line (fields/consumers mapped, examples/
      non-examples present for every supported language and every entity
      label currently in use).
- [x] `docs/adr/0004-curated-enrichment-registry-spike.md` exists, states
      a clear decision (STOP, not "adopt"/"iterate"/"do not adopt" —
      those Step 6 verdicts don't apply since Steps 2-5 never ran), and
      documents alternatives considered per the repo's ADR template.
- [x] `git diff --stat` confirms zero changes to `config.toml`,
      `noticiencias/config_schema.py`, `news_collector/config/settings.py`,
      `news_collector/enrichment/`, `news_collector/scoring/`,
      `news_collector/reranker/`, `tests/test_enrichment_pipeline.py`, or
      `tests/data/golden_articles.json` — production enrichment behavior
      is byte-identical to before this spike.
- [x] `plans/README.md` row for 048 updated TODO → PARTIAL with a
      one-line note pointing at the ADR.
