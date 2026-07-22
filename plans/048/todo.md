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

## Verification (original Step 1 pass)
- [x] `git diff --stat` (drift-check style, per the plan's own
      "Executor instructions") against `config.toml`,
      `noticiencias/config_schema.py`, `news_collector/config/settings.py`,
      `news_collector/enrichment/`, `news_collector/scoring/`,
      `news_collector/reranker/`, `tests/test_enrichment_pipeline.py`,
      `tests/data/golden_articles.json` → empty (no changes).
- [x] `plans/README.md` row for 048 updated to PARTIAL.
- [x] Root `spec.md` Sequencing state and root `todo.md` updated.

## Follow-up (2026-07-22): operator committed to self-review, resumed Steps 2-3
- [x] Operator confirmed (via AskUserQuestion) they'll personally
      review/label the corpus, async — STOP condition on "no reviewer"
      no longer applies. Documented honestly that this is one reviewer,
      not the plan's own two-reviewer-adjudication ask (labeling guide's
      "Single-reviewer limitation" section).
- [x] Built `tests/data/enrichment_eval.jsonl`: 44-record stratified seed
      (all 4 languages, all 6 topics + `general`, every adversarial case
      type the plan names). Draft topic/entity guesses kept in a
      separate `model_draft_*` field, never conflated with `gold_*`
      (left `null` until reviewed).
- [x] Wrote `docs/spikes/enrichment-corpus-labeling-guide.md`: labeling
      process, schema reference, corpus-growth instructions, the
      single-reviewer limitation, and the title+summary-vs-content
      finding below.
- [x] Built `scripts/validate_enrichment_corpus.py` (Step 2's own Verify
      criterion) + 7 tests incl. negative cases (duplicate id,
      dev/heldout overlap, invalid language, reviewed-with-null-gold,
      email-like text) proving each rejection actually fires.
- [x] Built `scripts/evaluate_enrichment_registry.py` (Step 3): micro/
      macro precision/recall/F1 for topics+entities, per-language
      slices, general/multi-label rates, latency, top FP/FN clusters,
      corpus/model-version hashes for reproducibility. Only scores
      `review_status="reviewed"` records — unreviewed drafts silently
      excluded, never counted as ground truth. `sufficient_evidence`
      field structurally false below 200 reviewed records. `--compare`
      errors rather than fabricating a candidate comparison (Step 4
      still not built).
- [x] Found and documented a real gap while self-testing: golden_articles.json's
      `science` topic tag depends on `content` text this corpus schema
      deliberately excludes (title+summary only, per Step 2's own spec)
      — not a scoring bug, fixed the test to isolate the arithmetic
      instead of asserting golden parity it structurally can't reach.
- [x] 12 tests total, all green:
      `tests/unit/enrichment/test_enrichment_registry_tooling.py`.
      `black`/`ruff` clean (scripts/ is mypy-excluded per existing repo
      convention).
- [x] End-to-end smoke test: both scripts run cleanly against the seed
      corpus (0/44 reviewed today, reports correctly reflect that).
- [ ] Reviewer labels records over time; re-run the evaluator once ≥200
      are reviewed (or informally sooner, understanding
      `sufficient_evidence` will read `false` until then).
- [ ] Steps 4-6 (candidate registry, paired comparison, adoption ADR)
      remain not attempted — depend on a real reviewed corpus existing.
