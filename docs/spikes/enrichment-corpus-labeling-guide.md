# Enrichment evaluation corpus: labeling guide (plan 048, Steps 2-3)

> Status update (2026-07-22): the operator confirmed they will personally
> review/label this corpus, asynchronously. Plan 048's own Step 2 language
> asks for **two** independent reviewers who adjudicate disagreements. With
> one reviewer, that specific inter-rater-adjudication process cannot happen
> as written — this guide documents that honestly (see "Single-reviewer
> limitation" below) rather than silently pretending it's a two-reviewer
> process. This does not change the corpus/tooling's validity; it changes
> what confidence to place in agreement statistics until a second reviewer
> is available.

## What you're labeling

`tests/data/enrichment_eval.jsonl` (schema below) is a seed corpus of 44
synthetic title+summary records, stratified across the 4 supported
languages (en/es/pt/fr), the 6 configured topics + `general` fallback, and
the adversarial cases the plan names (ambiguous acronyms, substrings,
missing accents, negation, multi-topic, hard negatives). Every record
currently has `"review_status": "draft_unreviewed"` and
`"gold_topics"`/`"gold_entities"` set to `null` — these are NOT usable as
evaluation evidence until you review them.

Each record also carries a `model_draft_topics`/`model_draft_entities`
field — my own draft guess at what the labels should be, generated while
building the corpus. **Treat these as a starting point to correct, never
as pre-approved gold.** The whole point of this review step is your
independent judgment, not rubber-stamping a model's own guess.

## How to label a record

1. Read `title` + `summary` only (not any other field) — the corpus is
   deliberately title+summary-only, per the plan's own spec. See "A real
   finding from building this corpus" below for why that matters.
2. Consult `docs/spikes/curated-enrichment-registry.md` (plan 048 Step 1)
   for the definitions: what each of the 6 topics + `general` means, what
   counts as a named entity vs. a synonym/alias, and the multi-topic /
   ambiguity rules already documented there.
3. Decide the correct `gold_topics` (a list; can be more than one, matching
   the shipped pipeline's own multi-topic semantics — cap at 5) and
   `gold_entities` (a list of surface strings, e.g. `"NASA"`, not labels).
4. If you agree with `model_draft_topics`/`model_draft_entities`, copy them
   into `gold_topics`/`gold_entities`. If not, write your own corrected
   list — don't feel obligated to keep any part of the draft.
5. Set `"review_status": "reviewed"`.
6. Add anything noteworthy to `reviewer_notes` (a few records already have
   a note explaining what the adversarial case is testing — read those
   first, they're hints, not answers).
7. Run the validator after each labeling session:
   ```bash
   python scripts/validate_enrichment_corpus.py tests/data/enrichment_eval.jsonl
   ```
   It will reject a `"reviewed"` record that still has `null` gold fields,
   flag anything that looks like personal data (email addresses, long
   digit runs), and confirm no id collisions or dev/heldout leakage.

## Growing the corpus toward 200 records

44 records is a seed, not the plan's own ≥200-record target. To add more:
copy the JSONL schema (one JSON object per line), keep the same
stratification balance (roughly even across the 4 languages and 6 topics +
`general`), and keep writing your own gold labels directly rather than
asking me to draft-and-approve at scale — the value of this step is your
independent judgment, and over-relying on model drafts for volume would
quietly turn this back into the single-source-of-truth problem the plan is
trying to avoid.

## Single-reviewer limitation (read before trusting any agreement number)

Plan 048's Step 2 asks for **two** reviewers labeling independently, with
disagreements adjudicated and label guidelines recorded from that process.
With one reviewer:

- There is no independent second opinion, so no inter-rater agreement
  score can be computed or reported — don't compute one, and don't cite
  a single-reviewer corpus as having "agreement" data.
- Label consistency depends on this guide being followed the same way
  across sessions, especially far apart in time. If you have time later,
  a light self-check — re-labeling a random ~10% of already-reviewed
  records without looking at your prior labels, then diffing — is a
  reasonable substitute self-consistency signal, though it's not the same
  as real inter-rater reliability.
- If a second qualified reviewer becomes available later, re-review a
  sample against their independent labels before treating this corpus as
  meeting the plan's original two-reviewer bar.

## A real finding from building this corpus

While self-testing the evaluator (`scripts/evaluate_enrichment_registry.py`)
against the existing 6 `tests/data/golden_articles.json` examples, scoring
those against their own `expected` topics (which were authored against
title+summary+**content** combined) showed measurably lower F1 than 1.0 for
title+summary alone — the pipeline picks up the `science` topic in several
goldens via a keyword match that only appears in the article's `content`
field ("scientists" in content substring-matches the "science" topic
keyword), not in the shorter title+summary text this corpus uses. This is
expected, not a bug: a title+summary-only evaluation will genuinely surface
fewer topic matches than a full-article one would. Keep this in mind when
labeling — a record's gold topics should reflect what's actually inferable
from title+summary alone, not what you'd guess a full article might
additionally contain.

## Schema reference

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique. Convention used so far: `{lang}-{topic-or-case}-{seq}`. |
| `split` | `"dev"` \| `"heldout"` | Held-out records must never be used to tune anything. |
| `language` | `"en"` \| `"es"` \| `"pt"` \| `"fr"` | |
| `provenance` | `"synthetic"` \| `"permissioned"` | This seed is all `"synthetic"` (written for this purpose). |
| `case_type` | string | `positive`, `general_fallback`, `ambiguous_acronym`, `substring`, `negation`, `missing_accent`, `multi_topic`, `hard_negative`. |
| `title` / `summary` | string | The only text the evaluator reads — see the finding above. |
| `model_draft_topics` / `model_draft_entities` | list | Unreviewed draft guess — correct or discard, never trust as-is. |
| `gold_topics` / `gold_entities` | list \| null | Null until reviewed; the actual evaluation ground truth once set. |
| `review_status` | `"draft_unreviewed"` \| `"reviewed"` | Gate the validator and evaluator both key off. |
| `reviewer_notes` | string | Free text; a few records already explain the adversarial case being tested. |

## Running the baseline evaluator once you have reviewed records

```bash
python scripts/evaluate_enrichment_registry.py \
  --model pattern_v1 \
  --corpus tests/data/enrichment_eval.jsonl \
  --output reports/evaluation/enrichment-pattern-v1.json
```

Only `"review_status": "reviewed"` records are scored — unreviewed drafts
are silently excluded (not counted as zero, not counted at all), so partial
labeling progress is always safe to evaluate against. The report's own
`sufficient_evidence` field stays `false` until at least 200 reviewed
records exist, matching the plan's own Step 3 Verify threshold.
