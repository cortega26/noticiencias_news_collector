# Spec: source ALT extraction (real descriptions before the fallback)

Status: in progress · 2026-09-29
Supersedes: the `spec-image-alt-nonblocking.md` approach (reverted).
Partially superseded: acceptance item 5 (blocking) by
`spec-alt-text-nonblocking.md` — the queue stays, the block is gone.

## Why the previous approach was wrong

The reverted change resolved blocked articles with
`"Ilustración editorial relacionada con <título>"`. That string is rejected by
the frontend pre-publish gate: `../noticiencias/scripts/pre-publish-gate.js`
runs `check-image-alt.js`, which fails the pipeline boilerplate prefix
(there is a frontend test for it: `tests/image-alt.test.ts` → *"fails the
pipeline boilerplate"*), and `npm run lint` / `validate:content` run the same
check. `resolve_hero_alt_text` recomputes the same boilerplate at the
editorial stage, so the article would still fail — only later and less
actionably (frontend CI instead of the backend Images-desk message).

The spec premise only looked at `content-quality.js` (`^imagen editorial de`).
The cross-repo contract was misunderstood; publication with a fake fallback
would trade a clear block for a worse one.

## Goal

Capture the description the source already provides, so articles whose
source carries usable alt text stop hitting the Images-desk block, while
articles with genuinely no description keep the current (correct) block.

Acceptance criteria:

1. `ImageExtractor` captures real alt text from, in priority order:
   `og:image:alt`, `twitter:image:alt`, DOM `img[alt]`, and finally the
   nearest `<figure><figcaption>` text.
2. Alt text that is empty, shorter than 5 characters, or boilerplate
   (`is_boilerplate_alt`: "imagen de …", "ilustración editorial relacionada
   con …") is discarded — never propagated.
3. `rss_collector` propagates the selected candidate's alt into
   `article["image_alt"]` (which `model_dump_for_storage` mirrors into
   `article_metadata.image_alt`).
4. Alt text is sanitized: whitespace collapsed, capped at 300 characters.
5. When no description exists, the `missing_alt_text` brief is queued and
   the run continues with the Spanish-headline fallback
   (`spec-alt-text-nonblocking.md`); it no longer blocks. No frontend
   changes.

## Implementation

- `news_collector/logic/parsers/image_extractor.py`
  - `ImageCandidate.alt: Optional[str] = None`.
  - `_extract_metadata`: read `og:image:alt` / `twitter:image:alt` once and
    attach each to its own candidate family (og alt never lands on twitter).
  - `_extract_from_dom`: `img[alt]`, else nearest `figure > figcaption`.
  - `_clean_alt`: normalize, reject short/boilerplate, cap length. Boilerplate
    detection reuses `news_collector.editorial.hero_alt.is_boilerplate_alt`
    (pure stdlib) instead of duplicating the prefix list (refactor trigger).
- `news_collector/collectors/rss_collector.py`
  - When the HTML-extracted candidate is selected, copy `img_cand.alt` into
    `cand["image_alt"]` if present.
- Tests
  - `tests/unit/parsers/test_image_extractor.py`: metadata alts, DOM alt,
    figcaption fallback, source isolation, boilerplate/short/empty rejection,
    whitespace normalization, length cap.
  - `tests/unit/collectors/test_rss_collector_images.py`: the existing
    og:image flow now also asserts `image_alt` propagation; a boilerplate
    source alt stays unset and the image still resolves as IMAGE_OK.
- Handler tests stay as they are on `main` (blocking path restored).

## Verification

```bash
.venv/bin/python -m pytest \
  tests/unit/parsers/test_image_extractor.py \
  tests/unit/collectors/test_rss_collector_images.py \
  tests/decompose_refinery/test_image_handler.py \
  tests/unit/editorial/test_hero_alt.py -q

make lint && make type && make test && make test-boundaries
make quality-gate
```

Edge cases covered: alt on a logo candidate (candidate dropped anyway),
twitter alt without og image, figcaption with extra whitespace/markup,
300-char cap, unicode text.

## Out of scope

- Vision/LLM-generated descriptions (follow-up; quotas).
- Feed-level alt fields (nothing parses them today).
- Any frontend gate/contract change.
- The Images-desk UI.
