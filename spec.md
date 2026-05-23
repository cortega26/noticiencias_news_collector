# Spec: Fix FallbackProvider missing _extract_json attribute

## Goals
- Fix the crash `'FallbackProvider' object has no attribute '_extract_json'` when processing headlines/metadata with `FallbackProvider` enabled.
- Ensure `FallbackProvider` exposes `_extract_json` by delegating to the primary provider in its chain.

## Implementation Details

### 1. LLM Factory Update
- In `news_collector/infrastructure/llm/factory.py`, add `_extract_json(self, text: str) -> Dict[str, Any]` to the `FallbackProvider` class.
- The method will return `self.providers[0]._extract_json(text)`.

## Verification

### Automated Tests
- Add a new test case in `tests/unit/infrastructure/llm/test_provider.py` (or a dedicated test file) that instantiates a `FallbackProvider` with a mock/real provider and verifies `_extract_json` delegates correctly.
- Run `make lint`, `make type`, and `make test` to ensure everything is correct.
