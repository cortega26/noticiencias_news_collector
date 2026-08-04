# Todo: Logs/Warnings/Errors/Concurrency (see spec-logs-warnings-concurrency.md)

## Baseline (BEFORE)
- [x] `make lint && make type && make test` green

## Item 1 — %s → {} migration
- [x] Migrate 14 sites in `storage/article_repository.py`
- [x] Migrate `storage/source_repository.py:161`
- [x] Migrate `infrastructure/llm/factory.py:282,303` (verified: stdlib logging — exempt, confirmed by meta-test)
- [x] Migrate `apps/refinery/main.py:788`
- [x] Fix singular/plural `system/bootstrap.py:156`
- [x] Meta-test: no `%`-style loguru placeholders repo-wide
- [x] `make lint && make type && make test` green

## Item 2 — nih_news
- [x] Blacklist entry in `news_collector/config/sources.yaml` (reason + date)
- [x] `make config-validate` green
- [x] Scrapling experiment (httpx/curl_cffi/Playwright) → recorded in blacklist_reason
- [x] Sanity: `_get_sources_to_process` skips it (unit test)

## Item 3 — NVIDIA retry policy
- [x] Extract `_should_retry` helper (sync + async exception shapes)
- [x] Wire into `generate_async` (fail fast on deterministic 4xx)
- [x] Wire into `generate_sync` (fail fast on deterministic 4xx)
- [x] Unit tests: 410/403/404 no-retry; 429/503/network retry
- [x] `make lint && make type && make test` green

## Item 4 — Bounded concurrency
- [x] `asyncio.Semaphore` in `collect_from_multiple_sources_async`
- [x] `max_concurrent_sources` in `config.toml` [collection] + code default 10
- [x] Tests: bound respected, completeness, semaphore release on exception
- [x] `make lint && make type && make test` green

## Final audit
- [x] Adversarial review of touched + adjacent code
- [x] Fix findings + add tests
- [x] Full suite green; summary report

### Audit findings (2026-08-04)
- **Item 1 (braces)**: AST scan of all converted call sites in 8 files → **0** literal/unbalanced `{`/`}` (format render safe). No module mixes stdlib+loguru (meta-test exclusion hole is theoretical only). Meta-test excludes `.venv`/`__pycache__`.
- **Item 2**: blacklist respected by `_get_sources_to_process` (tested); `sources.py` enforces reason+date; `nih_news` kept in file for re-enable. Scrapling experiment conclusive (redirected). `nih_news` scrapling experiment: httpx 403, curl_cffi 403 (`from scrapling import Fetcher`), Playwright headless intermittent 200/403 Cloudflare "security verification" → not reliable from this egress → blacklist correct.
- **Item 3**: spec said "no retry + log once" — matches implementation; circuit breaker still `record_error`. `pytest-timeout` (10s/test) discovered during tests → backoff stubbed to 0 in retry test. Ruff auto-fixed a redundant `if` in `_should_retry`. FallbackProvider now reaches Ollama faster on 410 (positive interaction).
- **Item 4 (spec correction)**: spec claimed `collection_config` is free-form with "no schema change"; reality: `config_manager` CLI validates `[collection]` via strict Pydantic `CollectionConfig` (`extra="forbid"` at `noticiencias/config_schema.py:224`) → added `max_concurrent_sources: PositiveInt = 10` to schema (critical config change) + regenerated `docs/config_fields.md`.
- **Verification**: runtime exposes `collection_config.max_concurrent_sources=10` (checked live).
