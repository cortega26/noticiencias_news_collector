# Plan 048 TODO

## Pre-work
- [x] Read the full plan file `plans/048-spike-curated-enrichment-registry.md`.
- [x] Recon via subagent: `config.toml`'s `pattern_v1` block (now
      lines 155-463, shifted from the plan's ~155-384 estimate due to an
      added sentiment lexicon), `config_schema.py`'s `TopicConfig`/
      `EntityPattern`/`EntityPatterns`/`ModelConfig`/`EnrichmentConfig`
      (now ~614-654, shifted from ~557-597), `settings.py`'s
      `_normalize_enrichment` (now ~128-160, shifted from ~75-107),
      `ConfigurableNLPStack` behavior (spaCy fallback, first-substring
      matching, label-discarding alias emission, 5-topic cap, cache
      keying), every real consumer (confirmed: feature scoring, reranker,
      serving API, image briefs — NOT `CognitiveScorer`, NOT monitoring/
      observability, contradicting the plan's own "monitoring" framing),
      `tests/data/golden_articles.json` (6 examples, all 4 languages, all
      6 topics, zero `general`/negation/substring/accent cases), and
      `tests/test_enrichment_pipeline.py` (pure exact-match regression,
      no precision/recall/FP/FN measurement).
- [x] Confirmed absent from schema (grep for `provenance`, `review_date`,
      `lifecycle`, `ownership`, `owner`, `registry_id`, `stable_id`):
      zero matches — the plan's "Current state" claim is accurate.

## Step 1: Editorial ontology and use cases
- [x] Wrote `docs/spikes/curated-enrichment-registry.md`: five-way label
      vocabulary, full consumer table with file:line, stable-ID/
      deprecation-link/cross-language-equivalence gap analysis (proposed
      vocabulary only, not implemented), allowed entity labels with
      examples/non-examples per language, ambiguity rules (the one
      existing case: `case_sensitive` on `TECH`/"IA"), multi-topic
      semantics (5-cap, declaration order, `topics[0]` privileged by
      image briefs), what `general` means (residual fallback, not a
      curated category), golden-example coverage gap summary.
- [x] Satisfies Step 1's own Verify line: fields/consumers mapped,
      examples/non-examples recorded per supported language and label.

## Steps 2-6: STOPPED
- [x] Invoked the plan's own STOP condition ("no qualified editorial
      reviewer or safe representative data") rather than fabricating a
      ≥200-record "two-reviewer-adjudicated" corpus with self-generated
      labels dressed as independent review.
- [x] Did NOT build the Step 3 evaluator script — the plan's own Step 3
      Verify line disqualifies the 6 existing goldens as sufficient
      evaluation evidence, so a scaffold that could only run against them
      would produce a non-evidential number; not built rather than built
      and mislabeled.
- [x] Wrote `docs/adr/0004-curated-enrichment-registry-spike.md`: STOP
      decision, context, consequences, 4 alternatives considered (incl.
      why fabricating labels was rejected), and concrete next steps for
      whoever resumes with a real reviewer + corpus.

## Verification
- [x] `git diff --stat` (drift-check style, per the plan's own
      "Executor instructions") against `config.toml`,
      `noticiencias/config_schema.py`, `news_collector/config/settings.py`,
      `news_collector/enrichment/`, `news_collector/scoring/`,
      `news_collector/reranker/`, `tests/test_enrichment_pipeline.py`,
      `tests/data/golden_articles.json` → empty (no changes).
- [x] `plans/README.md` row for 048 updated to PARTIAL.
- [x] Root `spec.md` Sequencing state and root `todo.md` updated.
