# Plan 054: Stop pytest from writing into the production log file

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 9a1e4a8..HEAD -- news_collector/utils/logger.py config.toml tests/conftest.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — additive, test-mode-only behavior change; no effect on production logging.
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `9a1e4a8`, 2026-08-07

## Why this matters

`data/logs/collector.log` and its rotated `.gz` snapshots are meant to be the record of real collector runs. Today they aren't: any test that triggers `get_logger()` (which happens implicitly through nearly every module's `logger = get_logger().create_module_logger(...)` pattern — `nvidia_provider.py`, `rss_collector.py`, dozens more) configures the same loguru file sink at `data/logs/collector.log`, because the path comes straight from `config.toml`'s `[logging].file_path` with no test-mode override anywhere.

This was confirmed directly on today's files: filtering `data/logs/collector.2026-08-07_11-49-31_138988.log.gz` by process ID separates one real collector run (PID 2215310, 11:49:31–12:34:52, the actual production activity) from roughly a dozen other short-lived PIDs — pytest worker processes — writing into the exact same file between 12:29 and 12:47. The polluted file contains fabricated URLs (`test-source.com`), `MagicMock` repr strings, synthetic SSRF probe targets, and made-up article IDs (`article 42`) interleaved with real production WARNING/ERROR lines. Anyone debugging a real incident from this file risks treating test fixtures as production evidence — during this session, "category classifier fallback" (69 occurrences) and "Auditor initialized with config missing ollama.api_url" (68 occurrences) both looked like real recurring problems until filtering by PID showed they were 100% test noise.

## Current state

- `news_collector/utils/logger.py:43-83` (`NewsCollectorLogger.configure_logging`) — reads `config = config or runtime_config.logging_config`, already has one precedent for an environment-based override:

```python
        # Override level from environment variable to support runtime changes (e.g. CLI args)
        import os

        env_level = os.environ.get("LOG_LEVEL")
        if env_level:
            # Create a copy to avoid mutating the global configuration
            config = config.copy()
            config["level"] = env_level
```

- `news_collector/utils/logger.py:138-170` (`_configure_file_handler`) — takes `config["file_path"]` verbatim and passes it to `logger.add(str(self.log_file_path), ...)`.
- `news_collector/utils/logger.py:344-358` (`get_logger()`) — process-wide lazy singleton; `configure_logging()` runs at most once per process (`is_configured` guard), so whichever config is in effect the *first* time any test imports something that triggers `get_logger()` decides the sink for the rest of that pytest worker's session.
- `config.toml:474-476`:
```toml
[logging]
...
file_path = "data/logs/collector.log"
```
- `tests/conftest.py` — no fixture touches logging configuration today; it only has `_close_global_db_manager` (autouse) and a `pytest_sessionfinish` hook for closing sqlite connections. No test in the repo reads `data/logs/collector.log` or asserts on its contents (verified: `grep -rln "data/logs/collector.log" tests/` returns nothing), so redirecting it during tests cannot break an existing assertion.
- Pytest sets `PYTEST_CURRENT_TEST` in the environment automatically for every test process during a test run (standard pytest behavior, no configuration needed) — this is the signal to key off, exactly like the existing `LOG_LEVEL` override uses `os.environ.get`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Lint | `make lint` | exit 0 |
| Types | `make type` | exit 0 |
| Unit tests | `make test` | all pass |
| Manual repro (before fix) | `rm -f /tmp/repro-collector.log; cp config.toml /tmp/repro-config.toml; python -m pytest tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py -q; ls -la data/logs/collector.log` | file exists and its mtime just updated (proves contamination pre-fix) |
| Manual repro (after fix) | same test run, then check no new lines were appended to `data/logs/collector.log` (compare `wc -l` before/after, or check mtime is unchanged) | mtime unchanged — proves the fix worked |

## Scope

**In scope**:
- `news_collector/utils/logger.py`

**Out of scope** (do NOT touch, even though related):
- `config.toml`'s `[logging]` section — the production `file_path` value stays as-is; this plan adds a runtime override, not a config change.
- `tests/conftest.py` — no fixture needed if the fix lives in `logger.py` keyed off `PYTEST_CURRENT_TEST` (see Step 1). Do not add a conftest fixture unless Step 1's approach turns out to be insufficient (see STOP conditions).
- Any other module's logger usage (`get_logger().create_module_logger(...)` call sites) — they don't need to change; the fix is centralized in `configure_logging()`.

## Git workflow

- Branch: `advisor/054-isolate-test-logging-sink`.
- Single commit is fine given the size of this change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Redirect the file sink when running under pytest

In `news_collector/utils/logger.py`, inside `configure_logging()`, immediately after the existing `LOG_LEVEL` override block (around line 67), add:

```python
        # Under pytest, never write to the production log file — tests
        # would otherwise share data/logs/collector.log with real collector
        # runs (confirmed: pytest worker PIDs interleaved with a real
        # collector run's PID in the same rotated log file). Redirect to an
        # isolated temp path instead of skipping file logging entirely, so
        # any future test that does want to assert on file-logging
        # behavior still can.
        if os.environ.get("PYTEST_CURRENT_TEST") is not None:
            import tempfile

            config = config.copy()
            config["file_path"] = str(
                Path(tempfile.gettempdir()) / "news_collector_test_logs" / "collector.log"
            )
```

Place this after the `LOG_LEVEL` block and before `logger.remove()`, so it participates in the same `config = config.copy()` pattern already established (don't mutate the shared `runtime_config.logging_config` object — the existing `LOG_LEVEL` block already establishes this convention; if both overrides fire, `config.copy()` must only happen once — reuse the `config` variable rather than copying twice).

`Path` is already imported at the top of the file (`from pathlib import Path`); `tempfile` is not — add the import at the top of the method (or top of file, matching the existing style where `import os` is a local import inside the method — follow that same local-import convention for `tempfile`).

**Verify**:
```
python -m pytest tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py -q
ls -la /tmp/news_collector_test_logs/collector.log
```
→ the temp file exists and was just written; `data/logs/collector.log`'s mtime is unchanged from before the test run.

### Step 2: Confirm production behavior is untouched

Run a quick manual check that `configure_logging()` still writes to `data/logs/collector.log` outside of pytest (where `PYTEST_CURRENT_TEST` is not set):

```
python -c "
from news_collector.utils.logger import get_logger
import os
assert 'PYTEST_CURRENT_TEST' not in os.environ
l = get_logger()
print(l.log_file_path)
"
```

**Verify**: prints a path ending in `data/logs/collector.log` (absolute path), confirming the override only fires under pytest.

## Test plan

- No new automated test is required — this is logging-infrastructure behavior that's awkward to unit test cleanly (it depends on `PYTEST_CURRENT_TEST` being set, which is true for *any* test that would try to verify it, making the test self-fulfilling). Rely on the manual verification commands in Steps 1 and 2 instead, and record their output in the PR description / commit message for reviewer confirmation.
- If you want a regression guard anyway, add one assertion to `tests/conftest.py`'s existing `pytest_sessionfinish` hook (or a new lightweight session-scoped autouse fixture) that checks `get_logger().log_file_path` does NOT resolve to the repo's `data/logs/collector.log` — but this is optional given the manual verification above; do not over-engineer it.

## Done criteria

- [ ] `make lint` exits 0
- [ ] `make type` exits 0
- [ ] `make test` exits 0 (no test depended on the old shared-file behavior — none currently reference `data/logs/collector.log`)
- [ ] Running any test suite subset does not change `data/logs/collector.log`'s mtime or line count (Step 1's verify command)
- [ ] Running the collector normally (outside pytest) still writes to `data/logs/collector.log` (Step 2's verify command)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 054 updated

## STOP conditions

- `PYTEST_CURRENT_TEST` turns out not to be reliably set in this repo's test invocation (e.g. a custom test runner that clears environment variables) — verify with `python -m pytest -q --collect-only -k nonexistent 2>&1; echo $PYTEST_CURRENT_TEST` inside a test to confirm before assuming Step 1 works; if it's unset, fall back to a `tests/conftest.py` autouse fixture that monkeypatches `news_collector.utils.logger.get_runtime_config` or sets `NEWS_COLLECTOR_TEST_MODE=1` explicitly in a `pytest_configure` hook instead, and report the change of approach.
- Some test elsewhere in the suite turns out to depend on `data/logs/collector.log` being written during tests (contradicts the `grep` finding in "Current state" — re-run it yourself: `grep -rln "log_file_path\|data/logs/collector" tests/`) — if found, report it and do not silently break that test.
- Any step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If the `[logging].file_path` config value itself is ever made test-aware upstream (e.g. via a separate `config.test.toml` loaded under pytest), this override becomes redundant — check for that before re-adding it in the future.
- This does not address `data/logs/collector.log` rotation policy or retention — out of scope, unrelated to the contamination issue.
- Historical rotated `.gz` files created before this fix (e.g. `data/logs/collector.2026-08-07_11-49-31_138988.log.gz`) remain contaminated; this plan only stops it going forward.
