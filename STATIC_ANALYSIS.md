# Static Analysis & Hygiene Review (Phase B)

## 1. Hotspot Analysis Table

| File                                | Function / Location                            | Issue                                                                                                          | Severity     | Recommended Fix                                                                                  |
| :---------------------------------- | :--------------------------------------------- | :------------------------------------------------------------------------------------------------------------- | :----------- | :----------------------------------------------------------------------------------------------- |
| `collectors/base_collector.py`      | `_enforce_domain_rate_limit`, `_backoff_sleep` | **Blocking I/O**: Uses `time.sleep()` inside methods called by async collectors. Blocks the entire event loop. | **CRITICAL** | Change to `async def` and use `await asyncio.sleep()`.                                           |
| `collectors/html_collector.py`      | `_extract_articles_from_html` (L174, L205)     | **Silent Failure**: `except: pass` swallows usage errors and parsing bugs.                                     | **High**     | Catch specific exceptions (`KeyError`, `ValueError`) and log warnings with context.              |
| `components/editorial/ai_editor.py` | `_send_prompt` (L114)                          | **Unsafe Timeout**: 900s (15m) timeout for LLM calls.                                                          | **High**     | Cap at 60-120s. Fail fast if LLM is hanging.                                                     |
| `apps/refinery/main.py`             | `main` (L279-655)                              | **Cyclomatic Complexity**: ~375 line "God function" handling Git, DB, and AI.                                  | **High**     | Refactor into `RefineryEngine` class with `sync_repos`, `process_batch`, `publish` methods.      |
| `collectors/html_collector.py`      | `collect_from_source` (L50)                    | **Async Hazard**: Uses `asyncio.run()` inside a method. Will crash if called from FastAPI/Celery.              | **High**     | Remove sync wrapper or use `nest_asyncio` only if strictly necessary. Prefer async-native entry. |
| `scoring/cognitive_scorer.py`       | `_get_from_cache` (L115)                       | **Silent Failure**: `except: pass` hiding DB corruption/locks.                                                 | **Medium**   | Log `warning` on cache read failure so it can be monitored.                                      |
| `scripts/reproduce_scoring_bug.py`  | Global scope                                   | **Risky Default**: Uses `datetime.now()` (naive) mixed with aware times.                                       | **Medium**   | Use `datetime.now(timezone.utc)`.                                                                |

## 2. Top 5 Recommended Fixes (This Week)

1.  **[Reliability] Fix Blocking Sleep**: Immediate refactor of `BaseCollector` rate limiting to be async-aware. This is likely causing performance issues and "hanging" collectors.
2.  **[Observability] Expose Silent Failures**: Replace `except: pass` in `HtmlCollector` and `CognitiveScorer` with `logger.warning()`. We need to know if parsers are failing 100% of the time.
3.  **[Resilience] Cap LLM Timeouts**: Reduce `ai_editor` timeout from 900s to 60s. The editorial process shouldn't stall for 15 minutes on a single article.
4.  **[Architecture] Decouple Refinery Script**: Extract the core loop of `apps/refinery/main.py` into a `RefineryPipeline` class in `news_collector/pipelines/` to make it testable.
5.  **[Safety] Remove `asyncio.run` wrapper**: Ensure `HtmlCollector` is called via `await` from the orchestrator, removing the dangerous `asyncio.run()` nested call.
