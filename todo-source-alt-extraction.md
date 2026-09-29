# Todo: source ALT extraction

Execution index for [`spec-source-alt-extraction.md`](spec-source-alt-extraction.md).

## Context

- [x] Reverted the non-blocking fallback change and confirmed the real
      frontend gate (`pre-publish-gate.js` → `check-image-alt.js`) rejects
      the boilerplate fallback; decision recorded in the spec.

## Implementation

- [x] `ImageCandidate.alt` + metadata `og:image:alt` / `twitter:image:alt`
- [x] DOM `img[alt]` + `figure > figcaption` fallback
- [x] `_clean_alt`: normalize, reject short/boilerplate, cap 300
- [x] `rss_collector`: propagate selected candidate alt to `cand["image_alt"]`
      (and `_process_article` now carries it into the model)
- [x] Parser tests (matrix + source isolation + limits + seeded invariants)
- [x] Collector tests (propagation + boilerplate ignored)

## Verification

- [x] Targeted pytest files green (57 + 21 passed across the touched suites)
- [x] `make lint` green
- [x] `make type` green (3408 passed; coverage ratchet OK — 92.71% vs 91.25%)
- [x] `make test` (3395 passed, 5 skipped) + `make test-boundaries` green
- [x] `make quality-gate` green
- [x] Inventory baseline refreshed for the new spec/todo pair
      (`inventory-check` → drift 0)

## Delivery

- [x] Commit, push `feat/source-alt-extraction`, open PR describing the
      reverted approach, the evidence, and the extraction design
