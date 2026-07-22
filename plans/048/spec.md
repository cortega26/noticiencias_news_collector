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

## Follow-up (2026-07-22): operator will self-review, Steps 2-3 tooling built

The operator confirmed they will personally review/label the evaluation
corpus, asynchronously — the STOP condition ("no qualified editorial
reviewer") no longer applies, though the plan's own ask for **two**
independent reviewers still can't be met with one person (documented
honestly, not silently downgraded — see the labeling guide's
"Single-reviewer limitation" section).

Built in this pass:
- `tests/data/enrichment_eval.jsonl` — a 44-record stratified seed corpus
  (all 4 languages, all 6 topics + `general`, every adversarial case type
  the plan names: ambiguous acronym, substring, missing accent, negation,
  multi-topic, hard negative). Every record is `"review_status":
  "draft_unreviewed"` with `gold_topics`/`gold_entities` set to `null` —
  a `model_draft_topics`/`model_draft_entities` field holds my own
  unreviewed guess, clearly separated from gold, for the reviewer to
  correct or discard. This is a seed toward the plan's ≥200-record
  target, not the target itself.
- `docs/spikes/enrichment-corpus-labeling-guide.md` — the labeling
  process, schema reference, how to grow the corpus, the single-reviewer
  limitation, and a real finding surfaced while building this (below).
- `scripts/validate_enrichment_corpus.py` — enforces Step 2's own Verify
  criterion (IDs, split, language, provenance class, gold topics/entities
  present whenever `review_status="reviewed"`, no personal-data-like
  text, no dev/heldout id overlap). 7 unit tests, including negative
  cases proving each rejection actually fires.
- `scripts/evaluate_enrichment_registry.py` — the Step 3 baseline
  evaluator, built now that a real (if small) corpus and reviewer exist.
  Only scores records with `review_status="reviewed"` — unreviewed
  drafts are silently excluded, never treated as ground truth. Reports
  micro/macro precision/recall/F1 for topics and entities, per-language
  slices, `general`/multi-label rates, latency, top FP/FN clusters, and
  a `sufficient_evidence` field that stays `false` below 200 reviewed
  records (matching the plan's own threshold structurally, not just in
  a comment). `--compare` is accepted per the plan's own CLI shape but
  errors rather than fabricating a comparison, since no candidate
  registry exists (Step 4 still not attempted).
- **A real finding while self-testing the evaluator**: scoring the
  existing 6 `golden_articles.json` examples (reused as a determinism
  check only) against their own `expected` topics showed less than
  perfect F1 for title+summary alone — those goldens' `science` topic
  tag depends on the word "scientists" appearing in the `content` field,
  which this corpus schema deliberately excludes (Step 2 asks for
  "title-summary records"). Not a bug — documented in the labeling guide
  so the reviewer expects title+summary-only labeling to genuinely
  undercount topics a full article might suggest.
- 12 tests total (`tests/unit/enrichment/test_enrichment_registry_tooling.py`):
  corpus validator structural checks + rejection cases, evaluator
  determinism (`evaluate()` called twice on the same input produces
  identical output except timing), the 6-goldens-marked-insufficient
  check, a scoring-math sanity check (predicted set to gold by
  construction ⇒ F1 must be exactly 1.0), and confirmation that
  unreviewed seed-corpus records are excluded from evaluation.

Still not attempted: Steps 4-6 (candidate registry prototype, paired
comparison, adoption ADR) — all depend on a real reviewed corpus
existing first, which is now in progress but not complete (0/44
reviewed today). Plan 048 stays PARTIAL, not DONE, until the reviewer
has labeled enough records to run a real (not sanity-check) baseline.

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
