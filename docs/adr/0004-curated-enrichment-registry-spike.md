# ADR-0004: Curated multilingual topic/entity registry spike (plan 048)

- **Date**: 2026-07-21 (Steps 2-3 tooling resumed 2026-07-22)
- **Status**: Superseded in part — the operator has since confirmed they
  will personally review/label the corpus (asynchronously). The STOP below
  no longer applies to "no reviewer available"; it is updated in place
  (not superseded by a new ADR number, since the underlying decision
  record and alternatives-considered reasoning are still accurate and
  worth keeping together). See "Update (2026-07-22)" at the end of this
  document. Steps 4-6 remain un-started pending a sufficiently large
  reviewed corpus.

## Context

Plan 048 asks for a governed quality spike on the topic/entity enrichment
registry: today it is a small static block in `config.toml` (`pattern_v1`,
version `2025.02-pattern-v1`) with no stable IDs, provenance, review dates,
lifecycle status, or ambiguity policy (see
`docs/spikes/curated-enrichment-registry.md` for the full field-by-field
mapping done as Step 1).

The plan's own Step 2 requires building "at least 200 derived/synthetic or
permissioned title-summary records," stratified across languages, topics,
and adversarial cases (ambiguous acronyms, negations, substrings, missing
accents, hard negatives), with **"two reviewers [who] should independently
label a statistically useful subset; adjudicate disagreements and record
label guidelines, not reviewer identity."** Step 3's baseline evaluator is
only evidentially meaningful once that corpus exists — the plan explicitly
says the 6 existing golden examples "are not counted as sufficient
evaluation evidence." Steps 4-6 (candidate registry prototype, paired
comparison, adoption decision) all depend on Steps 2-3's outputs.

This work is running as an unattended autonomous session (no human
available to review labels, adjudicate disagreements, or attest to
corpus provenance/safety in real time). The plan's own STOP conditions
anticipate exactly this:

> Stop at corpus/guidelines if there is no qualified editorial reviewer or
> safe representative data.

## Decision

**STOP at Step 2.** Complete only Step 1 (ontology, consumers, field
mapping — `docs/spikes/curated-enrichment-registry.md`) in this spike.
Do not fabricate a ≥200-record "two-reviewer-adjudicated" corpus by
generating both the text and the labels myself: doing so would produce
labels with no genuine independent human judgment behind them, dressed
in the language of editorial review ("adjudicated disagreements," "label
guidelines") that the plan requires to mean something real. That would
be fabricated governance — worse than not having a corpus at all, because
a later reader could reasonably mistake it for the real thing.

For the same reason, no Step 3 baseline evaluator was built in this
spike. An evaluator that can only ever run against 6 non-adversarial
golden cases (explicitly disqualified as evidence by the plan itself)
would produce a "baseline" number with no real evidential value — the
tool would look like progress without being able to support any decision
the plan actually needs. Steps 4-6 were not attempted; each depends on
Step 2/3 outputs.

## Consequences

**Easier now**: Any future implementer — human or agent, with a real
editorial reviewer available — has a complete, code-verified map of every
current consumer, field, and gap (Section-by-section in
`docs/spikes/curated-enrichment-registry.md`) to start from, instead of
having to re-derive it from the codebase. The five-way ontology
(editorial category / broad topic / named entity / synonym-alias / trend
term) and the concrete schema gaps (stable IDs, deprecation links,
cross-language canonical grouping, ambiguity policy, `general`'s meaning)
are already identified.

**Still required before Steps 2-6 can start**:
1. A named, qualified editorial reviewer (ideally two, per the plan) who
   can independently label a real evaluation subset and adjudicate
   disagreements.
2. A source of ≥200 representative title/summary records that is either
   synthetic-but-realistic (written for this purpose, not scraped) or
   drawn from permissioned/licensed text — the plan explicitly rules out
   scraping copyrighted corpora into git.
3. Once both exist, Step 3's baseline evaluator (`scripts/evaluate_enrichment_registry.py`,
   the exact CLI interface the plan already specifies in its "Commands
   you will need" table) becomes buildable as a real evidential tool,
   and Steps 4-6 can proceed in order.

**Unchanged**: `config.toml`'s `pattern_v1` block, `noticiencias/config_schema.py`,
and the production `default_model` are untouched by this spike, satisfying
the plan's own Done Criterion ("Production model/configuration remains
unchanged during the spike") and this session's cross-plan invariant
against policy-module changes without evaluation.

## Alternatives considered

| Option | Reason rejected |
|---|---|
| Generate a synthetic 200-record corpus and self-label it, presenting it as if independently reviewed | Fabricates the exact governance signal (independent human adjudication) the plan requires; a later reader could mistake synthetic self-labels for real editorial review — worse than stopping |
| Build the Step 3 evaluator now, run it only against the 6 existing goldens, and report those numbers as "the baseline" | The plan explicitly disqualifies the 6 goldens as evaluation evidence; publishing a "baseline" built on disqualified data creates false confidence for whoever reads this ADR later |
| Skip straight to Step 4 (prototype a candidate registry schema) without any baseline to compare against | Step 5's paired comparison and Step 6's adoption decision would have nothing real to be measured against — the plan's precision-floor and non-regression requirements are meaningless without Step 3's baseline |
| Do nothing at all (skip plan 048 entirely) | Step 1's ontology work has standalone value (already true today, independent of the corpus gate) and directly satisfies the plan's own Step 1 Verify criterion — leaving it undone would waste that value for no safety benefit |

## Next steps (for whoever resumes this plan)

1. Identify and name a qualified editorial reviewer (ideally two, for
   independent labeling per the plan's Step 2 language).
2. Source or commission ≥200 representative, legally safe title/summary
   records per the stratification the plan specifies (languages, six
   topics + `general`, ambiguous acronyms, negations, substrings, missing
   accents, aliases, multi-topic, hard negatives).
3. Build `scripts/evaluate_enrichment_registry.py` per the plan's
   "Commands you will need" table, using the real corpus from step 2 as
   the first meaningful input.
4. Resume at Step 3 in `plans/048-spike-curated-enrichment-registry.md`.

## Update (2026-07-22): operator will self-review, Steps 2-3 tooling built

The operator confirmed directly that they will personally label the
evaluation corpus, asynchronously. This resolves next-step 1 above in
part — a reviewer now exists — but not fully: the plan's own Step 2
language asks for **two** independent reviewers who adjudicate
disagreements, and one person cannot do that. This is documented
honestly (see `docs/spikes/enrichment-corpus-labeling-guide.md`'s
"Single-reviewer limitation" section) rather than silently treated as
equivalent to the original two-reviewer bar.

What changed as a result:
- `tests/data/enrichment_eval.jsonl`: a 44-record synthetic, stratified
  seed corpus now exists (next-step 2 above, partially — 44 of the
  ≥200 target), with draft topic/entity guesses clearly separated from
  gold labels (which stay `null` until the operator reviews them).
- `scripts/validate_enrichment_corpus.py` and
  `scripts/evaluate_enrichment_registry.py` (next-step 3) are both
  built and tested — the evaluator only ever scores reviewed records
  and structurally reports `sufficient_evidence: false` below 200
  reviewed records, so it cannot be mistaken for a real baseline while
  the corpus is this small.

This ADR's original STOP decision — do not fabricate two-reviewer-
adjudicated labels — still stands and was not violated: no labels were
fabricated, only tooling and a to-be-reviewed seed corpus were built.
Steps 4-6 (candidate registry, paired comparison, adoption decision)
remain un-started; they depend on a real reviewed corpus of meaningful
size, which is now in progress but not complete.

## Update (2026-08-13): corpus reviewed (44), Steps 3-5 executed, Step 6 = iterate

The operator reviewed and gold-labeled the 44-record seed corpus
(`tests/data/enrichment_eval.jsonl`, `review_status="reviewed"`), which
unblocked the plan's evidence chain at small-but-real scale. This update
records what the evidence shows and the honest Step 6 decision it
supports — and does not support.

### What was done

- **Step 3 baseline** (production `pattern_v1` / `2025.02-pattern-v1`,
  corpus sha `cb54f4efca79`): topics P 0.818 / R 0.752 / F1 **0.767**;
  entities P 0.773 / R 0.705 / F1 0.546; `general`-fallback rate 0.318.
  `sufficient_evidence` is structurally `false` (44 < 200 reviewed).
- **Step 4 candidate**: `scripts/enrichment_candidate.py` (model version
  `2026.08-curated-candidate`) — an evaluated pattern-set update, kept
  outside `config.toml` per the plan's isolation rule. `--compare` was
  wired into `scripts/evaluate_enrichment_registry.py` (previously an
  honest error stub).
- **Step 5 paired comparison** (same corpus, both models, deterministic):

  | Metric | baseline | candidate | delta |
  |---|---|---|---|
  | topics F1 | 0.767 | **0.911** | +0.144 |
  | topics P | 0.818 | 0.943 | +0.125 |
  | topics R | 0.752 | 0.910 | +0.158 |
  | entities F1 | 0.546→0.773* | **0.750→0.924*** | +0.151* |
  | entities P | 0.773→0.886* | 0.773→0.955* | — |
  | entities R | 0.705→0.886* | 0.795→0.966* | — |
  | `general` rate | 0.318 | 0.204 | −0.114 |

  *Methodology refinement (2026-08-13, QW1): the evaluator now passes the
  record's `language` (per-record language scoping, previously default-en)
  and compares entities accent-folded (plan 048's own "missing accents"
  adversarial case: canonical accented aliases vs accent-free gold labels
  were being counted as FN+FP simultaneously — an evaluation artifact).
  Baseline topics F1 is 0.866 under the refined methodology.
  | latency mean/p95 | 0.98/1.16 ms | 1.04/1.41 ms | +0.06/+0.25 ms |

  17/44 records change topics/entities. Raw paired counts, no bootstrap
  (sample too small for meaningful CIs). The accent-normalization artifact
  noted in the original write-up was resolved in-session (2026-08-13,
  QW1): the literal matcher now accent-folds case-insensitive patterns
  (`_fold_accents` in `nlp_stack.py`), so canonical accented patterns match
  accent-free article text; the evaluator folds accents on both sides of
  the entity comparison so gold/canonical accent variants count as one
  entity. Remaining measured signals are small and real: FN `ESA` (1,
  language-scoping), FN `Amazonia` (1, no pattern), FP `Ministère de la
  Santé` (1) and `NASA` (1).
- **Critical-slice review (plan's STOP trigger)**: one genuine
  regression was found and fixed — the candidate's added
  `satellite`/`satélite` space keywords made `pt-climate-pos-019` (Amazon
  climate monitoring via satellite data) gain a spurious `space` label.
  Keywords removed; re-run confirms the FP is gone (F1 0.911 after fix)
  and no other sensitive slice regresses. One unresolved pre-existing FN
  documented: `en-science-pos-005` ("cell regeneration" study) misses
  `health` in both baseline and candidate — a keyword-coverage gap, not
  a candidate regression.
- **Downstream consumers** (from Step 1's map): feature scoring
  (`feature_scorer.py` entity-richness), topic-diversity reranking
  (`reranker.py`), serving API filters (`api.py`), and image briefs
  (`image_briefs.py` uses `topics[0]` as the brief's scientific domain).
  Impact direction: multi-label rate rises (fewer `general` fallbacks),
  entity richness rises slightly (higher entity recall), `topics[0]`
  changes for ~4 records. All additive (more correct labels), none
  structural.

### Step 6 decision: **iterate** (do not adopt yet)

- **Why not adopt**: the plan's own Step 2/3 Verify lines set ≥200
  reviewed records as the evidence bar for an adoption decision; 44 is a
  sanity check, not a baseline. Adopting on 44 would repeat the
  fabricate-evidence mistake this ADR exists to prevent — in the other
  direction (overclaiming).
- **Why not discard**: direction is consistent across every metric
  (topics +0.144 F1, entities +0.204 F1, `general` −0.114, no remaining
  critical-slice regression, +0.06 ms mean latency) and the candidate is
  pure static config — zero runtime/rollback risk to trial at scale.
- **Therefore**: keep `scripts/enrichment_candidate.py` as the candidate
  registry, keep production default `pattern_v1` untouched (Done
  criterion satisfied), and treat the next milestone as ≥200 reviewed
  records → re-run the identical evaluator → adopt/do-not-adopt on that
  evidence, with this ADR's thresholds (no critical-slice regression;
  precision floor 0.90 topics on the 200+ corpus).
- **Owner/cadence**: operator (single reviewer — two-reviewer
  adjudication remains documented as a limitation, not silently
  downgraded). Re-evaluation cadence: every 50 newly reviewed records,
  formal decision at ≥200.
- **Rollback safety**: candidate is not wired into runtime config; if it
  were, rollback is one config revert (plan 033 versioning applies). No
  cache-mixing risk while it stays out of production.

The original STOP decision and its rationale stand; this update is the
operator-review milestone that plan's "Next steps" anticipated.
