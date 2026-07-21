# Plan 048: Spike a curated multilingual topic and entity registry

> **Executor instructions**: Evaluate quality offline against the current pattern model. Do not switch the production default model or enlarge the runtime schema until the corpus, metrics, governance, and rollback decision pass. Update plan 048 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat e43bd30..HEAD -- config.toml noticiencias/config_schema.py news_collector/config/settings.py news_collector/enrichment news_collector/scoring news_collector/reranker tests/test_enrichment_pipeline.py tests/data/golden_articles.json docs`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: plans/027-complete-stage4-wiring-and-cache.md, plans/033-make-config-refresh-live.md
- **Category**: direction
- **Planned at**: backend `e43bd30`, 2026-07-21

## Why this matters

Topic/entity enrichment affects ranking, API filtering, image briefs, monitoring, and editorial context, but the current multilingual registry is a small static block inside `config.toml`. A curated registry with provenance and offline evaluation could improve LatAm relevance and explainability. The net-positive first step is a governed quality spike, not an unmeasured expansion of keyword lists.

## Current state

- `config.toml:155-384` selects `pattern_v1` version `2025.02-pattern-v1`, supports English/Spanish/Portuguese/French, defines 15 named entity patterns, and six keyword topics plus `general` fallback.
- `noticiencias/config_schema.py:557-597` permits topic keyword maps and entity label/pattern/alias/case-sensitivity, but no stable registry IDs, provenance, review dates, lifecycle status, ambiguity rules, or ownership.
- `news_collector/config/settings.py:75-107` normalizes validated entries into runtime pattern maps.
- `ConfigurableNLPStack` falls back from optional spaCy to patterns, matches entities by first substring occurrence, emits canonical aliases without labels, caps topics at five, and caches by model version/language/text.
- `tests/data/golden_articles.json` contains only six positive multilingual examples; `tests/test_enrichment_pipeline.py` asserts exact outputs but does not measure false positives, false negatives, ambiguity, per-language quality, or drift.
- Downstream scoring rewards entity richness, reranking uses topics for diversity, and the serving API exposes/filter topics, so quality changes can alter editorial outcomes beyond enrichment itself.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Baseline evaluation | `.venv/bin/python scripts/evaluate_enrichment_registry.py --model pattern_v1 --corpus tests/data/enrichment_eval.jsonl --output reports/evaluation/enrichment-pattern-v1.json` | versioned per-language/topic/entity metrics and error slices are emitted |
| Candidate comparison | `.venv/bin/python scripts/evaluate_enrichment_registry.py --model curated_candidate --compare pattern_v1 --corpus tests/data/enrichment_eval.jsonl --output reports/evaluation/enrichment-curated-candidate.json` | paired deltas, latency, and changed examples are emitted |
| Golden regression | `.venv/bin/python -m pytest tests/test_enrichment_pipeline.py tests/spikes/test_enrichment_registry.py -q` | deterministic existing behavior and registry validation fixtures pass |
| Full backend gates | `make lint && make typecheck && make test` | exit 0; production default remains unchanged during spike |

## Scope

**In scope**: taxonomy/label policy, representative derived-text evaluation corpus, registry schema/provenance proposal, curator/reviewer workflow, offline baseline/candidate evaluator, error analysis, runtime/cost benchmark, downstream impact sample, and build/adopt/no-build ADR.

**Out of scope**: scraping copyrighted corpora into git, changing production `default_model`, an admin UI, online self-training, accepting LLM suggestions without human review, replacing source editorial categories, or tuning ranking weights.

## Git workflow

- Branch: `advisor/048-curated-enrichment-spike`.
- Commit example: `research: evaluate curated enrichment registry`.
- Keep the candidate registry/evaluator isolated from runtime configuration until the ADR approves adoption.

## Steps

### Step 1: Define the editorial ontology and use cases

List every consumer and distinguish editorial category, broad topic, named entity, synonym/alias, and trend term. Define stable IDs, allowed entity labels, topic hierarchy/deprecation rules, multilingual equivalence, ambiguity rules, multi-topic semantics, and what `general` means. Prioritize LatAm scientific/public-interest coverage rather than exhaustiveness.

**Verify**: `docs/spikes/curated-enrichment-registry.md` maps each field/consumer and records examples/non-examples for every supported language and label.

### Step 2: Build a representative, legally safe evaluation corpus

Create at least 200 derived/synthetic or permissioned title-summary records stratified across languages, sources, six current topics, `general`, ambiguous acronyms, negations, substrings, missing accents, aliases, multi-topic stories, and hard negatives. Two reviewers should independently label a statistically useful subset; adjudicate disagreements and record label guidelines, not reviewer identity.

**Verify**: corpus validator enforces IDs, split, language, text provenance class, gold topics/entities, no raw personal data, and no overlap between development and held-out sets; report agreement and slice counts.

### Step 3: Establish the current baseline

Implement a deterministic offline evaluator around the shipped pipeline. Report exact/micro/macro precision, recall, and F1 for topics/entities; per-language/per-label slices; `general`/coverage/multi-label rates; latency/memory; and top false-positive/negative clusters. Preserve model/config/corpus hashes.

**Verify**: repeated runs are identical except timing; the six existing golden cases remain regression tests but are not counted as sufficient evaluation evidence.

### Step 4: Prototype a governed registry outside production config

Define candidate entries with stable ID, type/label, canonical display name/topic, language, aliases/pattern, boundary/case/normalization policy, provenance, rationale, owner, reviewer, created/reviewed dates, lifecycle status, and replacement/deprecation link. Add schema/lint checks for duplicates, alias collisions, overly broad tokens, unreachable/deprecated targets, missing translations, and version bump discipline.

**Verify**: invalid/ambiguous fixture entries fail with actionable locations; candidate compilation is deterministic and does not mutate `config.toml`.

### Step 5: Compare candidates and downstream effects

Run paired baseline/candidate evaluation on held-out data and sample changes through feature scoring, topic-diversity reranking, API filtering, monitoring distributions, and image briefs. Review every regression in sensitive health/climate/economy slices. Set minimum precision floors and non-regression guardrails before looking at candidate results.

**Verify**: report includes bootstrap confidence intervals or raw paired counts, slice regressions, latency/memory delta, changed downstream rankings, and a human-reviewed error table; aggregate improvement cannot hide a critical-language/topic regression.

### Step 6: Decide adoption and staged rollout

Compare keeping config-only patterns, adopting a separate reviewed registry/compiler, or using an external/provider model. Score accuracy, explainability, curator effort, runtime/dependency cost, refresh/rollback safety, and ownership. If approved, specify shadow evaluation, versioned model rollout, cache invalidation, monitoring, rollback, and a later production implementation plan.

**Verify**: ADR states `adopt`, `iterate`, or `do not adopt`, quantitative thresholds/results, owner/cadence, registry location, migration scope, and review date. Production default is still `pattern_v1` at spike completion.

## Test plan

- Registry schema/lint tests for duplicates, collisions, lifecycle, provenance, and determinism.
- Held-out multilingual positive, negative, ambiguous, substring, accent, and multi-label evaluation.
- Existing enrichment golden/regression suite.
- Downstream scoring/reranking/API/monitoring sample comparison and latency/memory benchmark.

## Done criteria

- [ ] Ontology, consumers, governance, and ownership are explicit.
- [ ] Representative held-out corpus and reproducible current baseline exist.
- [ ] Candidate quality and downstream effects are measured by language/topic/entity slice.
- [ ] Adoption ADR and staged rollout/rollback decision are complete.
- [ ] Production model/configuration remains unchanged during the spike.

## STOP conditions

- Stop at corpus/guidelines if there is no qualified editorial reviewer or safe representative data.
- Stop adoption if precision floors regress in a critical language/topic even when aggregate F1 improves.
- Stop if plan 033 cannot guarantee model-version/cache refresh consistency; a registry rollout must never mix versions silently.

## Maintenance notes

If adopted, require owner/reviewer/provenance for every entry, periodic drift/error-slice review, semantic versioning, reproducible compilation, and one-command rollback to the prior registry/model version.
