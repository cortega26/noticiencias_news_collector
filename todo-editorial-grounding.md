# TODO: editorial grounding

- [x] C1: pure `grounding.py` + unit tests (2315 fixture)
- [x] C1: `scripts/grounding_backtest.py` (URL-verified source matching) + results in docs
- [x] C2b: advisory `grounding` stage in `refinery_engine` (never blocks; fail-open; short source -> `skipped_reason`)
- [x] C2a: hygiene repair (U+2011/U+202F/U+00A0/zero-width) over the whole refined file in `refinery_engine` (stage `text_hygiene`, recorded only when something changed)
- [x] C2c: "Verificación de grounding" section in the content PR body (`format_pr_section` -> `PROrchestrator.create_pr(review_notes=...)`)
- [ ] Optional: unit-conversion handling (B -> mil millones) before considering blocking
- [ ] Optional: independent `fact_check` with a different provider
