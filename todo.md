# Todo: Fix FallbackProvider missing _extract_json attribute, incorrect timeout override, and blocked image_alt fallback

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

- [x] **Phase 4: Replace blocked default image_alt text**
  - [x] Replace `"Imagen editorial de"` fallback string in `news_collector/logic/workflows/refinery_engine.py`.
  - [x] Replace `"Imagen editorial de"` fallback string in `news_collector/logic/workflows/image_handler.py`.
  - [x] Replace `"Imagen editorial de"` fallback string in `news_collector/logic/workflows/image_briefs.py`.

- [x] **Phase 5: Final Validation**
  - [x] Run `make lint`, `make type`, and `make test`.
