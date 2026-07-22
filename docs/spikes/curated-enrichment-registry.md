# Spike: editorial ontology for a curated enrichment registry (plan 048, Step 1)

> Status: Step 1 only. Steps 2-6 are STOPPED — see
> `docs/adr/0004-curated-enrichment-registry-spike.md`. This document does not
> change runtime behavior; `config.toml`'s `pattern_v1` block and
> `noticiencias/config_schema.py` are unmodified.

## Purpose

Plan 048 asks for an editorial ontology before any registry redesign work:
who consumes topics/entities today, what each field currently means, and
what a stable, governed schema would need to add. This document is that
ontology. It is descriptive (what exists today, read directly from the
code) plus a proposed vocabulary (what a future registry would need) — it
does not propose or ship a new schema.

## 1. The five kinds of label, and what exists today

The plan asks the ontology to distinguish five conceptually different
things that the current system collapses into two flat structures
(`topics: Dict[str, TopicConfig]` and `entities: EntityPatterns`,
`noticiencias/config_schema.py:614-632`):

| Kind | Definition | Current representation | Stable ID today? |
|---|---|---|---|
| **Editorial category** | The source's own top-level bucket (e.g. `category: "science"` on a `Source`) | Separate from enrichment entirely — comes from source config, not the NLP stack | N/A (source-defined) |
| **Broad topic** | A coarse subject bucket assigned by keyword match (`space`, `science`, `health`, `technology`, `climate`, `economy`) | `TopicConfig.keywords: Dict[str, List[str]]` — the topic's *name* (the dict key, e.g. `"space"`) doubles as its only identifier | No — the string key is the ID; renaming it silently breaks anything that persisted the old string |
| **Named entity** | A concrete proper noun (org, place, event, product) mentioned in text | `EntityPattern(label, pattern, alias, case_sensitive)` — but the emitted `NLPResult.entities` tuple carries only the alias/surface string, the `label` is discarded before it reaches any consumer (`nlp_stack.py:224-227`, confirmed no consumer reads a label) | No — no `id` field exists on `EntityPattern` at all |
| **Synonym/alias** | An alternate surface form that should resolve to the same canonical entity or topic | `EntityPattern.alias` (entity-level only) — topics have no alias concept; two different keyword strings in the same topic's list are just independent keywords, not declared synonyms of one canonical term | N/A |
| **Trend term** | A time-bounded, non-editorial keyword (not evaluated by this system at all) | `BasicScorer._evaluate_trending_topics` (`basic_scorer.py:667-703`) — a **separate, hardcoded word list matched directly against title+summary text**, entirely independent of `enrichment.topics`/`entities`. It is not a registry consumer and out of scope for this spike | N/A |

**Non-example**: "IA" (Spanish/Portuguese for AI) is configured as a
`TECH`-labeled entity with `alias="IA"` and `case_sensitive=true`
(`config.toml` entity block) precisely because case-insensitive matching
would collide with the unrelated word "ia" (Portuguese third-person
"goes/will"). This is the one case-sensitivity rule in the current
config, and it exists as an ad hoc per-entry flag, not a documented
ambiguity policy.

## 2. Every real consumer, and what it reads

Confirmed by direct code reading, not inference:

| Consumer | File:line | Reads | How it uses it |
|---|---|---|---|
| Feature scoring | `news_collector/scoring/feature_scorer.py:245-278` | `entities` (count only, not identity) | `richness = min(len(entities) / entity_target_count, 1.0)`, blended into content-quality score at weight `0.2` (`config.toml`, `scoring.content_quality_heuristics`) |
| Reranking (topic diversity) | `news_collector/reranker/reranker.py:1-58` | `topics` (list) | Per-topic cap during ranking: an article is skipped once its topic(s) have each hit `floor(limit * topic_cap_percentage)` accepted articles, enforcing diversity across the surfaced list |
| Serving API | `news_collector/serving/api.py:59,167-177,222-232,245,369,417` | `topics` (list) | Exposed as a response field; also a `?topic=` query filter via `json_extract(...) LIKE`-style substring match against the stored JSON |
| Image brief generation | `news_collector/logic/workflows/image_briefs.py:106-151` | `topics[0]` only | Fallback source for `scientific_domain` when no explicit domain/category is set, feeding the image-generation prompt template |
| Monitoring/observability | `news_collector/observability/enrichment_metrics_store.py` and `news_collector/monitoring/*.py` | *(nothing)* | Confirmed by grep: zero references to topic/entity content anywhere in the metrics/monitoring layer. It tracks pipeline health (attempt/success/failure/cost) only, never enrichment *content*. Plan 048's Why-this-matters framing ("monitoring") should be read as "the metrics *about* enrichment runs," not a topic/entity consumer |
| `CognitiveScorer` (LLM scorer) | — | *(nothing)* | Confirmed: zero `topic`/`entit` references. It defers entirely to LLM judgment and never reads the pattern-based registry output |

**Consequence for governance**: only 4 of the 6 places the plan's
"why this matters" section names actually read topic/entity content
(scoring, reranking, API, image briefs). A registry change's blast
radius is smaller than "ranking, API filtering, image briefs,
monitoring, and editorial context" suggests — monitoring tracks
enrichment *health*, not enrichment *output*, and the entity *label*
(`ORG`/`LOC`/etc.) currently reaches no consumer at all, only the
surface alias string does. Any future registry that wants label-aware
consumers (e.g., API filtering by entity type) would need to add that
consumer, not just add the field to config.

## 3. Stable IDs (proposed vocabulary, not implemented)

Today: a topic's identity *is* its config-file key string; an entity's
identity *is* its regex pattern string. Both break silently on rename
and have no way to express "this topic replaced that one."

Proposed for any future registry (not built in this spike):
- Every topic and every entity gets an opaque `id` (e.g. `topic.space`,
  `entity.org.nasa`) independent of its display string, so renaming a
  display label never breaks a persisted reference.
- A `replaces` / `deprecated_by` link field so a topic or entity can be
  retired without breaking historical data that was tagged with it
  (addresses the plan's "topic hierarchy/deprecation rules" requirement).

## 4. Allowed entity labels

Current labels in use (from `config.toml`'s entity blocks): `ORG`, `LOC`,
`EVENT`, `PRODUCT`, `TECH`, plus a schema-level default of `MISC`
(`EntityPattern.label: str = "MISC"`, `config_schema.py:621`) that is
declared but never actually assigned to any configured entry today.

| Label | Examples (current config) | Non-example |
|---|---|---|
| `ORG` | NASA, Google, ESA, IMF, ONU (es), Ministerio de Salud de Chile, UNAM, Telefónica, Universidade de São Paulo, Agence spatiale européenne | A generic company mention with no configured pattern is simply invisible — not mislabeled, just never extracted (the system has no NER fallback beyond spaCy, and spaCy itself falls back to patterns when unavailable) |
| `LOC` | Mars, Amazônia | A country name not in the pattern list is invisible, same caveat |
| `EVENT` | Artemis II | A one-off event not pre-registered is invisible |
| `PRODUCT` | Orion, Ariane 6 | — |
| `TECH` | IA (case-sensitive alias) | Lowercase "ia" in Portuguese running text must NOT match — this is the one documented ambiguity rule in the current system |
| `MISC` | *(declared, unused)* | — |

Since the label is discarded before reaching any consumer today (Section
2), "allowed labels" is currently an authoring-time-only concept — it
constrains what the config author can write, not what any downstream
system can filter or reason about.

## 5. Multilingual equivalence

Each `ModelConfig.languages` is `["en", "es", "pt", "fr"]`
(`config.toml`); every entity and topic entry is keyed `shared` (applies
in all languages) plus optional per-language additions/overrides. There
is no cross-language canonical-form linkage today beyond this flat
union — e.g., "NASA" (shared, works in all four languages because it's
an acronym) versus "Agence spatiale européenne" (French-only phrase for
the same underlying real-world organization, ESA) are two entirely
independent pattern entries with no declared relationship. A future
registry that wants "this French phrase and this English acronym name
the same entity" would need an explicit canonical-entity-id grouping
that does not exist today.

**Example (equivalence gap)**: "European Space Agency", "ESA", and
"Agence spatiale européenne" are three surface forms of one real-world
organization but appear in config as unrelated shared/`en`/`fr` pattern
entries with no shared canonical ID.

## 6. Ambiguity rules

The only ambiguity handling that exists today is `case_sensitive` on
`EntityPattern` (used exactly once, for `TECH`/"IA"). There is no
documented policy for:
- **Acronym collision** (e.g., an acronym that is also a common word in
  another supported language).
- **Substring collision**: entity matching is first-`str.find()` based
  (`nlp_stack.py:219`), so a short pattern that is a substring of a
  longer unrelated word will false-positive; no word-boundary or
  minimum-length rule is enforced today.
- **Negation**: "NASA has NOT confirmed..." still extracts `NASA` as an
  entity and, if "space" keywords are present, still assigns the
  `space` topic — sentiment is scored independently of entity/topic
  extraction, so there is no mechanism today to suppress or flag a
  negated mention.

Any future registry proposal (Step 4, STOPPED — see the ADR) would need
explicit rules here before evaluation, since the plan's own Step 2
corpus is required to include "ambiguous acronyms, negations,
substrings, missing accents" as held-out test cases precisely to
measure whether a candidate registry improves or worsens these failure
modes — which is impossible to score without the corpus.

## 7. Multi-topic semantics

`_infer_topics` (`nlp_stack.py:260-284`) returns every topic whose
keyword set matched, capped at 5 (`tuple(detected.keys())[:5]`), in
config-declaration order (not match-strength order — there is no
scoring/ranking among matched topics, just presence/absence per topic
then a hard slice). Consumers that read `topics` (reranker, API, image
briefs) all treat the list as unordered/first-item-privileged
(image briefs uses `topics[0]` specifically, so declaration order in
`config.toml` silently determines which topic wins the image-domain
fallback — an implicit priority signal that isn't documented as such
anywhere in the config schema).

## 8. What `general` means

`default_topic = "general"` (`config.toml:170`) is **not** a topic with
its own keyword list — it is the value substituted only when the
keyword-matching loop over all configured topics produces zero matches.
It behaves as a residual/fallback bucket, not a genuine editorial
category, and no golden example currently exercises it (Section 9). Any
registry proposal must decide whether `general` remains a residual
fallback or becomes a real, curated catch-all category with its own
review criteria — this spike does not decide that (see ADR).

## 9. Current golden-example coverage (for reference — not the Step 2 corpus)

`tests/data/golden_articles.json` has 6 examples, one per
language/topic-combination, covering all 4 languages and all 6 declared
topics at least once. It has **zero** examples of: the `general`
fallback, negation, substring/acronym collision, missing accents, or an
entity appearing without its expected topic. `tests/test_enrichment_pipeline.py`
asserts exact list equality against these 6 cases only — it is a
regression guard, not an evaluation corpus, and the plan's own Step 3
Verify criterion explicitly says these 6 cases "are not counted as
sufficient evaluation evidence." Building the real ≥200-record
stratified corpus described in Step 2 is the blocked step — see the ADR.

## Summary: what this document establishes

- A five-way vocabulary (editorial category / broad topic / named
  entity / synonym-alias / trend term) mapped onto the two structures
  that exist today.
- The true consumer list (4 real content consumers, not 5; monitoring
  consumes health metrics, not content; `CognitiveScorer` consumes
  neither).
- The concrete gaps a future registry schema would need to close:
  stable opaque IDs, deprecation/replacement links, cross-language
  canonical grouping, an explicit ambiguity policy, and a decision on
  what `general` should mean.
- This satisfies plan 048 Step 1's own Verify criterion (mapped
  fields/consumers, examples/non-examples per language and label). It
  does not perform Steps 2-6.
