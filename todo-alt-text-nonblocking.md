# TODO — non-blocking hero alt text

- [x] `image_handler._resolve_downloaded`: resolve with placeholder +
      queued `missing_alt_text` brief instead of `resolved=False`
- [x] `hero_alt.resolve_hero_alt_text`: fallback = Spanish title (passes
      frontend `check-image-alt`)
- [x] Update `tests/decompose_refinery/test_image_handler.py`
      (auto-alt, IMG-10, IMG-11 now non-blocking)
- [x] Update `tests/unit/editorial/test_hero_alt.py` fallback expectations
- [x] Update `test_ai_editor_coverage.py::test_hero_alt_recomputed_in_spanish`
- [x] Add integration case: downloaded image w/o alt ⇒ publish continues
- [x] `make lint`
- [x] `make type` equivalent: mypy + full suite (3450 passed) + ratchet
      (92.89% vs 91.25%)
- [x] `make test-contracts`, `make test-boundaries`, `make quality-gate`,
      `make docs-check`, `make plans-ledger-check`
- [x] `make inventory-refresh` (also heals pre-existing plans/117 drift)
- [ ] After committing the new spec/todo pair: `git add` them, re-run
      `make inventory-refresh`, commit the inventory (it only tracks
      committed paths)
