# Editorial grounding check — parked

**Status:** parked (not a priority). **Found:** 2026-09-19, reviewing front-end PR #188
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
