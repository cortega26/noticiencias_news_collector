# Spec — non-blocking hero alt text (fail-open on missing alt)

## Problem

`ArticleImageHandler._resolve_downloaded` (path 2: HTTP image downloaded)
returns `resolved=False` when the source alt is missing/boilerplate and no
usable human alt-brief exists (`spec-alt-text-brief-flow.md`). The whole
Refinery run fails with "Hero alt text required for article 2671…" even
though the article and its image are fine.

Product rule: **a publication request cannot fail just because it could
not find an alt text.** Today's fail-fast existed only because the
Spanish fallback stamped the pipeline boilerplate
(`Ilustración editorial relacionada con …`), which the frontend
`check-image-alt` gate rejects. The fallback is the root cause; the block
was the workaround.

## Design (fail-open, gate-passing fallback, advisory brief)

1. `image_handler._resolve_downloaded`: when no usable alt exists
   (source alt boilerplate + no usable alt-brief), do **not** block:
   - queue the `missing_alt_text` brief (Images desk follow-up, as today),
   - log a warning,
   - return `resolved=True` with the placeholder alt; the Spanish
     recompute happens later in frontmatter assembly (plan 079).
2. `hero_alt.resolve_hero_alt_text`: replace the boilerplate fallback
   `Ilustración editorial relacionada con {título}` with the Spanish
   headline itself. Good alts and human brief alts still pass through
   untouched; without a title, keep current value (parity).
   This is what keeps the frontend gate green: title-as-alt already
   exists in the published corpus and `check-image-alt` only rejects
   empty, `Imagen de …`, and the old boilerplate prefix.
3. Human brief alts still win; a boilerplate brief alt still does not
   self-accept (keeps the queue actionable).
4. No change to the "no image at all" blocks (missing source image,
   download failure, site logo): the frontend requires an `image`, so
   those stay fail-closed.

## Files

- `news_collector/logic/workflows/image_handler.py` — `_resolve_downloaded`
  returns resolved + advisory brief; docstrings updated.
- `news_collector/editorial/hero_alt.py` — fallback is the Spanish title;
  module/function docs updated.
- Tests: `tests/decompose_refinery/test_image_handler.py`,
  `tests/unit/editorial/test_hero_alt.py`,
  `tests/unit/editorial/test_ai_editor_coverage.py`,
  `tests/integration/test_refinery_image.py` (end-to-end non-blocking case).

## Acceptance

- Boilerplate/missing source alt + no brief → `resolved=True`,
  `queued_brief=True`, run continues, `missing_alt_text` brief queued.
- Frontmatter `image_alt` for that article is the Spanish headline
  (non-empty, not the old boilerplate, not English).
- Usable brief alt → still used verbatim (plan 079 behavior kept).
- Missing image (no URL / failed download / site logo) → still blocks.
- `make lint && make type && make test` green.

## Verification

- Unit: updated handler matrix + hero_alt matrix.
- Integration: downloaded image without alt ⇒ `process_single_article`
  returns True, editor called, brief queued.
- Manual: reproduce article 2671 shape (image URL, no alt) → no
  "Blocked before publish" line.
