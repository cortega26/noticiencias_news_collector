# Spec: editorial grounding check (phase C1)

## Goals
Detect generated-article claims unsupported by the source (figures, vague
quantities, scope/population claims, hype, typography) with deterministic,
explainable rules; measure their precision on published posts before anything
blocks publication.

## Design
- `news_collector/editorial/grounding.py`: pure (stdlib + PyYAML), fail-open,
  same pattern as `editorial/readability.py`. `check_grounding(markdown,
  source_text, allow_terms, min_source_chars)` -> `GroundingReport`
  (`findings`, `errors`, `warnings`, `stage_details()`); `normalize_text_hygiene()`
  repairs U+2011/U+202F/U+00A0/zero-width characters.
- `scripts/grounding_backtest.py`: read-only; matches a post's source in the DB by
  `refinery_id` **and** URL; skips short/unmatched sources.
- Not wired into the refinery flow in this phase.

## Verification
- Unit: 2315-defect fixture (recall), number formats/words/space-grouped thousands,
  "figure + millones" not vague, source equivalents allowed, LatAm framing rule,
  short-source skip, hygiene repair, invalid frontmatter, glossary/sources ignored,
  backtest script URL matching.
- Real: backtest over the published posts (results in docs/editorial_grounding_check.md).
- `make lint && make type && make test`, coverage ratchet.

## Next (C2)
Advisory `grounding` stage after `readability` in `refinery_engine`, hygiene repair in
`AIEditor._repair_output`, PR-body section, count in the run report.
