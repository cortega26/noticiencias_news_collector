# Todo: Fix FallbackProvider missing _extract_json attribute and incorrect timeout override

- [x] **Phase 1: Implement fallback delegation**
  - [x] Add `_extract_json` method delegating to `self.providers[0]` in `news_collector/infrastructure/llm/factory.py`.

- [x] **Phase 1.5: Fix timeout computation in FallbackProvider**
  - [x] Retrieve `old_timeout = getattr(provider, "timeout", None)` before calculating `current_timeout` in `generate_sync` and `generate_async`.
  - [x] Use `timeout or old_timeout or 60` for the final provider in `generate_sync` and `generate_async`.

- [x] **Phase 2: Establish tests**
  - [x] Add a unit test verifying `FallbackProvider._extract_json` in `tests/unit/infrastructure/llm/test_provider.py`.

- [x] **Phase 2.5: Test timeout computation**
  - [x] Add unit tests verifying final provider timeout behavior under `FallbackProvider` in `tests/unit/infrastructure/llm/test_provider.py`.

- [x] **Phase 3: Validation**
  - [x] Run `make lint` and `make type`.
  - [x] Run `make test` to verify all tests pass.
