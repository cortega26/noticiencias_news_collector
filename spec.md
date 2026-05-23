# Spec: Fix FallbackProvider missing _extract_json attribute and incorrect timeout override

## Goals
- Fix the crash `'FallbackProvider' object has no attribute '_extract_json'` when processing headlines/metadata with `FallbackProvider` enabled.
- Ensure `FallbackProvider` exposes `_extract_json` by delegating to the primary provider in its chain.
- Fix the timeout logic in `FallbackProvider.generate_sync` and `FallbackProvider.generate_async` to preserve the final fallback provider's default timeout (e.g. 3600 seconds for `ai_editor.py`) rather than overriding it to 60 seconds.

## Implementation Details

### 1. LLM Factory Update
- In `news_collector/infrastructure/llm/factory.py`, add `_extract_json(self, text: str) -> Dict[str, Any]` to the `FallbackProvider` class delegating to `self.providers[0]._extract_json(text)`.
- Update the timeout computation inside the provider iteration loops in `generate_sync` and `generate_async`. Specifically, retrieve `old_timeout = getattr(provider, "timeout", None)` first, and then calculate:
  `current_timeout = 60 if i < len(self.providers) - 1 else (timeout or old_timeout or 60)`
  This keeps fast failover (60s) for early providers but respects the configured/original timeout for the final provider in the fallback chain.

## Verification

### Automated Tests
- Test in `tests/unit/infrastructure/llm/test_provider.py` that verifies `FallbackProvider` correctly computes and restores timeout for the final provider when invoking both sync and async generations.
- Run `make lint`, `make type`, and `make test`.
