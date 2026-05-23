# Todo: Fix FallbackProvider missing _extract_json attribute

- [x] **Phase 1: Implement fallback delegation**
  - [x] Add `_extract_json` method delegating to `self.providers[0]` in `news_collector/infrastructure/llm/factory.py`.

- [x] **Phase 2: Establish tests**
  - [x] Add a unit test verifying `FallbackProvider._extract_json` in `tests/unit/infrastructure/llm/test_provider.py`.

- [x] **Phase 3: Validation**
  - [x] Run `make lint` and `make type`.
  - [x] Run `make test` to verify all tests pass.
