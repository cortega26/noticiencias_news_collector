# Editorial grounding check

**Status:** implemented, advisory only. C1 (pure module + backtest), C2a (typography repair, stage `text_hygiene`), C2b (stage `grounding`), C2c (PR-body section). Blocking is deliberately not enabled (see backtest). **Found:** 2026-09-19, reviewing front-end PR #188
(article 2315, a bioRxiv preprint on alginate-encapsulated SC-islets).

## Problem

The article passed every automated gate (schema, tags, links, Codacy after a
fix) yet contained content **not supported by the source text**:

- invented specifics: "miles de células", "del tamaño de un grano de arena",
  "decenas de personas", "meses in vivo" (source: up to 98 days);
- external claims presented as facts: "millones de personas en América Latina",
  "rodent / immunodeficient models", fibrosis, GMP manufacturing;
- a title metaphor that misstates the subject ("Perla de alginato" for
  alginate microspheres);
- Spanish quality defects: missing verb, untranslated "bead", "insulin-producing",
  special non-breaking hyphens (U+2011) and narrow spaces (U+202F);
- `fact_check` items all marked `confirmed`, but produced by the same model that
  wrote the text (self-assessment, not independent verification).

The post was corrected by hand in the front-end PR. The pipeline gap remains.

## Idea (not designed or implemented)

A deterministic *grounding* pass before publication:

1. **Numeric grounding:** every number, percentage, duration and unit in the
   generated fields (`title`, `excerpt`, `summary_points`, `why_it_matters`,
   `fact_check`, body) must appear in the source text (normalize `%`, `±`,
   thousands separators, Spanish/English decimals).
2. **Named-entity grounding:** institutions, places and populations
   ("América Latina", "McGill") must occur in the source or in an explicit
   allow-list (site context such as the LatAm audience framing).
3. **Overclaim lexicon:** flag "miles", "millones", "decenas", "solución de
   salud pública", "revolucionario", etc. unless grounded.
4. **Text hygiene:** reject/normalize U+2011, U+202F/U+00A0 runs, and untranslated
   English glossary terms ("bead", "insulin-producing").
5. **Independent fact_check:** verify claims against the source with a *different*
   model/provider than the writer (the provider chain now allows this), or
   downgrade unverifiable items from `confirmed` to `unverified`.

## Where it would live

Policy modules (validation/editorial) are network-free per AGENTS.md, so items
1–4 fit the existing deterministic repair/validation layer (see
`news_collector/editorial/` and `news_collector/validation/rules.py`); item 5
needs the LLM chain and belongs in the editorial council/auditor flow.

## Open questions

- Blocking (fail publication) vs advisory (warn + mark in PR body)?
- False-positive rate on real articles: measure on the last ~30 published posts
  before enabling anything blocking.
- Should `why_it_matters` be allowed to add context beyond the source (labelled
  as editorial context) instead of being forbidden from it?

## Phase C1 — implemented (advisory, not wired)

`news_collector/editorial/grounding.py` (`check_grounding(markdown, source_text)`,
pure, fail-open) and `scripts/grounding_backtest.py` (read-only). Rules:
`number` (error), `vague_quantifier` (error), `scope_claim`, `overclaim`,
`hygiene`, `fact_check` (warn). Checked fields: title, excerpt, summary_points,
why_it_matters, fact_check, headlines_variants, confidence, uncertainty_note, body
(glossary/sources are reference material). Sources under 1500 chars are skipped
(`skipped_reason="source_too_short"`): a feed teaser is not what the article was
written from. América Latina framing is allowed in `why_it_matters` (editorial voice).

### Backtest (2026-09-20, local DB)
Of 26 posts with a `refinery_id`, only **7** could be checked: older posts' ids no
longer point at the same rows (the stored URL must match `source_url`), and short
teaser sources are skipped. On those 7: 5 have >=1 `error`; per post: hygiene 5.1,
vague_quantifier 1.4, number 0.9. Reading the findings:

- **hygiene is the clearest win**: U+202F/U+2011 appear in nearly every recent post
  (thin space before `%`/units, non-breaking hyphens) -> deterministic repair in C2.
- `vague_quantifier` hits are mostly real generalisations ("cientos de miles de
  años", "millones de personas en todo el mundo") — the defect class of 2315.
- `number` false-positive class: unit conversions ("30B" in the source vs
  "30 000 millones" in the text) and rounding ("~60"). Not blocking-grade.
- Not detectable by these rules (known gaps): metaphors that misstate the subject
  ("Perla de alginato"), duration paraphrases ("meses in vivo" for 98 days),
  "tamaño de un grano de arena", "decenas de personas" when the source has no count.

Conclusion: keep advisory. Blocking would need the unit-conversion FPs handled and a
larger backtest (the 2315 original text is not preserved; it is reproduced as a
fixture from the defects listed above).

## Phase C2 — wired into the refinery (advisory)
Order in `refinery_engine`: `editor_refinement` -> `text_hygiene` (repair, only if it changed
something) -> `grounding` (advisory stage; findings persisted in the attempt summary) ->
`readability`. Findings also appear in the content PR body under "Verificación de grounding"
so the human merge review sees them. First real e2e (article 2372, LLM real, Git/PR simulated):
14 stages OK in 42 s, 28 characters repaired, 0 grounding findings (all body figures present in
the source, verified by hand).
