# Plan 079 — Codex P2 root fixes (hero alt + spillover scan)

## Findings (PR #144, chatgpt-codex-connector, both P2)

1. **Boilerplate EN alt**: `image_alt: Ilustración editorial relacionada
   con Lightning strikes kill thousands...` — `image_handler.py:56`
   stamps the fallback with `article["title"]`, which at image time is
   still the ENGLISH original (translation happens later). Screen
   readers get boilerplate + English.
2. **`tendencies` in body**: single-word EN spillover the translation
   critic missed (it hunts fused fragments, not lone words).

## Design (backend-only, deterministic, fail-open; frontend already
// renders alt text — no frontend change)

A. Hero alt (`news_collector/editorial/hero_alt.py`, stdlib-only):
   `is_boilerplate_alt` (prefixes `ilustración editorial relacionada
   con`, `imagen de`) + `resolve_hero_alt_text(image_alt,
   spanish_title)`: keeps good brief alts verbatim; replaces empty or
   boilerplate with the Spanish fallback; list input takes first
   element; empty title keeps current value (parity, never worse).
   Hooked in `ai_editor.py` frontmatter assembly where `final_title`
   (Spanish) is known; log when replaced. Full visual description
   stays a human-brief concern (follow-up: vision model).
B. Spillover scan (`readability.py`): `check_english_spillover`
   over the publishable body (frontmatter/fences/code/URLs stripped;
   quoted + italic spans blanked per voice rules) against a curated
   high-precision lexicon (~24 unambiguous words with Spanish
   equivalents). One warn-level issue per word with sentence context.
   Hooked next to the headline check in `process_article` (log only).

Non-goals: vision-model alts, full-dictionary spellchecking (brand/
loanword false positives), blocking on findings, frontend edits, fixing
the two PR #144 instances in code (delivered as ready diffs).

## Verification

- Unit: alt matrix (EN boilerplate→ES, good kept, empty, list,
  `imagen de`); spillover (flagged, quoted/italic/fence/URL passes,
  clean pass); sentence context present.
- Integration: boilerplate-EN alt + Spanish direct ⇒ frontmatter alt
  in Spanish without the English title.
- Existing alt test (`test_image_alt_and_passthrough_fields`) intact.
- `make lint && make type && make test`.
