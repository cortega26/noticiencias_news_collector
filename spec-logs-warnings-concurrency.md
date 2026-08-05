# Spec: Log formatting, source health, NVIDIA retry policy, bounded concurrency

Task root: backend repo. Companion checklist: `todo-logs-warnings-concurrency.md`.
Baseline (BEFORE any change): `make lint && make type && make test` — recorded green.

## Item 1 — Loguru `%s` → `{}` migration (19 sites) + plural fix

Root cause: `utils/logger.py` uses loguru (formats `{}`), but ~19 call sites use
Python-logging `%s` style → literal `%s` in output, args silently dropped
(land in loguru `extra`), and `logger.error("...%s", e)` loses tracebacks.

Sites (exclude `.venv`):
- `storage/article_repository.py` lines 331, 686, 750, 762, 765, 782, 987, 992, 1217, 1281, 1308, 1338, 1360, 1380
- `storage/source_repository.py` line 161
- `infrastructure/llm/factory.py` lines 282, 303
- `apps/refinery/main.py` line 788

Also fix `system/bootstrap.py:156` singular/plural ("1 fuentes fallando").

Regression guard: repo-wide meta-test asserting no loguru call site uses `%`-style
placeholders (scans `news_collector/`, `apps/refinery/`, `scripts/` excluding venvs),
so this bug class cannot return.

## Item 2 — nih_news source health

`www.nih.gov/news-releases/feed.xml` → 403 even with browser User-Agent (verified
2026-08-04; already produced DLQ files and trips circuit breaker / health warnings).
Use the documented blacklist feature (`sources.yaml` comments: blacklisted +
blacklist_reason + blacklisted_date). `_get_sources_to_process` already skips
blacklisted sources. Entry stays in the file for future re-enable.

## Item 3 — NVIDIA: no retries on deterministic 4xx

`integrate.api.nvidia.com` returns 410/403/404 for accounts missing the "Public
API Endpoints" entitlement (known NVIDIA issue, 2026). Current code retries ALL
errors (`nvidia_provider.py` async:317-350, sync:415-446) → wasted attempts.

Extract pure helper `_should_retry(exc) -> bool`: True for network errors
(`httpx.RequestError` / `requests.RequestException`), 429, 5xx; False for other
4xx. When False → log once and raise immediately (no backoff sleep). Circuit
breaker semantics unchanged (still `record_error`).

Tests: unit tests for `_should_retry` (sync + async variants), and behavior tests
asserting a 410 does not retry (single attempt) while a 503 does.

## Item 4 — Bounded concurrency in async collection

`BaseCollector.collect_from_multiple_sources_async` already fans out one task per
source with `asyncio.gather` (unbounded — ~53 RSS sources at once). Add
`asyncio.Semaphore(max_concurrent_sources)` around `_process_single_source_async`.

Config: new `[collection] max_concurrent_sources = 10` in `config.toml`; code
fallback default 10 via `get_runtime_config().collection_config.get(..., 10)`.
`collection_config` is a free-form `Dict[str, Any]` (runtime.py:37) — no schema
change, but run `make config-docs-check` if docs generation touches it.

Tests (extend `tests/unit/collectors/test_base_collector.py`):
- bound is respected (max concurrent ≤ N, measured with a counter + sleeps)
- all source results still returned (completeness), incl. per-source exceptions
- semaphore release on exception (leak guard)

## Final: adversarial audit

Review all touched paths + adjacent code for sad paths/edge cases; fix findings;
extend tests. Full suite + `make lint && make type` re-run at the end.
