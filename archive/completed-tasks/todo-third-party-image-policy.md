# TODO — third-party source images are not reused as the hero image

- [x] `contracts/image_brief.py`: add `third_party_image_blocked` reason
- [x] `image_handler.py`: `REMOTE_IMAGE_ALLOWLIST`, `remote_image_hosts`,
      `_remote_image_allowed`, block path 2 by default
- [x] `tests/conftest.py`: autouse fixture allowing `example.com`
- [x] `tests/decompose_refinery/test_image_handler.py`: policy tests
- [x] Fix any publication test that relied on downloading a non-example host
      (none needed: they all use `example.com`)
- [x] Lint/format: black, isort, ruff clean
- [x] `make type` equivalent: mypy targets clean; unit suite with coverage
      (3570 passed); coverage ratchet OK (89.10% vs baseline 88.44%)
- [x] Integration suite (108 passed)
- [x] `make test-contracts` (226 passed), `make test-boundaries` (3 passed),
      `make quality-gate`, `make docs-check`, `make plans-ledger-check`
- [x] `make inventory-check`: not refreshed on purpose. `origin/main` already
      reports 86 drifted lines before this change (the weekly inventory
      workflows heal it); this change only adds this spec/todo pair.
- [x] Note in `docs/PRODUCT_FLOW.md` that scraped hero images are no longer
      reused by default
