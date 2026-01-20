# Test Gaps & Coverage Audit

## Critical Gaps (Must Fix)

### 1. `RSSCollector` Parsing Logic (0% Isolation Coverage)

- **Current State**: Tests rely on `test_rss_collector.py` mocking `requests`.
- **Gap**: No tests verify that specific XML structures (Atom vs RSS vs Bozo) are parsed correctly without network glue.
- **Fix**: After extracting `RssParser`, add `tests/unit/test_rss_parser.py` with static XML fixtures.

### 2. `AsyncRSSCollector` Concurrency

- **Current State**: `test_async.py` exists but checks success/fail.
- **Gap**: No test verifies that multiple feeds are actually fetched in parallel (e.g. total time < sum of individual delays). The blocking sleep bug went undetected because of this.
- **Fix**: Add `tests/perf/test_concurrency.py` using `asyncio.sleep` mocks.

### 3. `Refinery` Pipeline

- **Current State**: `test_refinery_source_clone.py` checks git ops.
- **Gap**: No tests for the internal logic of selecting articles, calling LLM, and generating markdown. It's all buried in `main`.
- **Fix**: After refactoring `RefineryEngine`, add unit tests for `engine.process_article()`.

## Missing Integration Tests

- **End-to-End Ingestion**: A test that inputs a mock RSS feed and asserts specific DB rows are created with correct normalized fields.
- **Scoring Replay**: A test that keeps a golden set of articles and asserts their scores don't drift (Regression Guardrail).

## Existing Test Assets (Leverage These)

- `tests/test_text_cleaner.py`: Good coverage of normalization. Keep it.
- `tests/test_reranker.py`: Good coverage of scoring math.
