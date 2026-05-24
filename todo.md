# Todo: Malicious Prompt Injection Protection in News Ingestion

- [x] **Phase 1: Implement prompt injection guard rule**
  - [x] Add `PromptInjectionGuardRule` class to `news_collector/validation/rules.py` with triggers and security exemptions.
  - [x] Register `PromptInjectionGuardRule` in `ContentValidator._get_default_rules` in `news_collector/validation/validator.py`.

- [x] **Phase 2: Add validation tests**
  - [x] Add unit tests verifying prompt injection blocks and exemptions in `tests/validation/test_validator.py`.

- [x] **Phase 3: Validation and Verification**
  - [x] Run `make lint`.
  - [x] Run `make type`.
  - [x] Run `make test` to ensure all tests (including new ones) pass.
