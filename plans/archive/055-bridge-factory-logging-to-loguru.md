# Plan 055: Bridge `factory.py`'s stdlib logging into the project's loguru sink

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 9a1e4a8..HEAD -- news_collector/infrastructure/llm/factory.py`
> If this file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW — pure logging-channel change; no behavior, timing, or control-flow change.
- **Depends on**: none functionally, but land it alongside (or before) plans 051 and 053 — those add new `logger.info`/`logger.warning` calls inside `FallbackProvider` (skip-degraded messages) that are silently dropped today for the exact reason this plan fixes.
- **Category**: bug
- **Planned at**: commit `9a1e4a8`, 2026-08-07

## Why this matters

`news_collector/infrastructure/llm/factory.py:15` sets up its logger with Python's stdlib `logging` module (`logger = logging.getLogger("news_collector.infrastructure.llm.factory")`) instead of the project's loguru-based `get_logger()` pattern used everywhere else (`nvidia_provider.py:29`, `rss_collector.py`, and effectively every other module logger in `news_collector/`). There is no bridge anywhere in the codebase connecting stdlib `logging` to loguru's sinks (`logging.getLogger().addHandler(InterceptHandler())` or equivalent — verified absent by search).

The practical effect: every message `FallbackProvider` logs — which providers it's attempting, which it's skipping as degraded, which failed and why it's falling back — never reaches the console or `data/logs/collector.log`. This was proven directly during a live e2e session on 2026-08-07: two real pipeline runs were executed specifically to observe `FallbackProvider`'s NVIDIA/Ollama routing decision, and neither the console nor the resulting log file contained a single line from this logger (`grep -c "infrastructure.llm.factory\|FallbackProvider" data/logs/collector.log` → `0`, across a file containing thousands of lines from those same runs). The auditor performing that session could not determine, even with direct log access, whether a given call was served by NVIDIA or silently fell back to Ollama.

This is a known category of bug in this codebase, just missed here: commits `71d2888` ("fix(logging): migrate loguru call sites from %-style to braces") and `e6a3d36` ("test(logging): guard unbalanced braces in loguru messages") already did this exact migration elsewhere and added a regression guard, `tests/unit/utils/test_logger_style.py`. That guard explicitly **exempts** any file matching `import logging` + `logger = logging.getLogger(...)` (`_is_stdlib_logging()`, `test_logger_style.py:47-50`) on the reasonable assumption that such a file is intentionally using stdlib logging and formats `%s` correctly for it — true in isolation, but it means `factory.py` was never flagged as broken, because the guard has no way to know this particular stdlib logger is actually disconnected from every sink. Converting `factory.py` to `get_logger()` removes it from that exemption, which means Step 3 below gets a stronger automatic check than a one-off grep: `test_logger_style.py`'s two scans (`test_no_percent_style_loguru_placeholders`, `test_no_unbalanced_braces_in_loguru_messages`) will start covering this file for the first time and will fail the build if any of the 10 call sites in Step 2 keeps a `%s` placeholder or picks up an unbalanced brace.

This isn't hypothetical impact: plans 051 and 053 (NVIDIA degradation failover and its hardening) add their most user-facing "the system just skipped a dead provider" signal as `logger.info`/`logger.warning` calls inside this exact file (`_is_degraded` skip messages, the generic "Provider X failed... proceeding to fallback" warning). Once those plans land, their new messages will be just as invisible as the ones already there, unless this plan lands too.

## Current state

`news_collector/infrastructure/llm/factory.py:1-16`:

```python
"""Provider Factory for LLM connections."""

import logging
from typing import Any, Dict, Generator, Optional, Union, cast

from news_collector.infrastructure.llm.gemini_provider import GeminiProvider
from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.infrastructure.llm.rate_limiter import (
    LLMRateLimitConfig,
    LLMRateLimiter,
)
from noticiencias.config_manager import load_config

logger = logging.getLogger("news_collector.infrastructure.llm.factory")
```

The exemplar to match, `news_collector/infrastructure/llm/nvidia_provider.py:27-29`:

```python
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("infrastructure.llm.nvidia_provider")
```

**Critical detail — format-string style differs between the two logging systems.** Every call site in `factory.py` today uses `%`-style placeholders (stdlib `logging` convention: `logger.info("Skipping degraded provider %s during generate_sync", provider.__class__.__name__)`). Loguru does **not** interpolate `%s`/`%d` — it formats messages with `str.format()` (`{}`) semantics, exactly like every `logger.warning("...{}...", value)` call in `nvidia_provider.py`. Swapping only the `logger =` line without also converting every call site's placeholders will not error, but will silently ship literal `%s` text with the arguments dropped — worse than the current silence, because it looks like a working log line. All 10 call sites (listed in Step 2) must be converted together with the logger swap.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Lint | `make lint` | exit 0 |
| Types | `make type` | exit 0 |
| Unit tests | `make test` | all pass |
| Format-string regression guard | `python -m pytest tests/unit/utils/test_logger_style.py -v` | all pass — `test_no_percent_style_loguru_placeholders` and `test_no_unbalanced_braces_in_loguru_messages` now scan `factory.py` for the first time (see "Why this matters") and are the authoritative check that Step 2's conversion is complete and correct; a leftover `%s` or an unbalanced `{}` fails one of these, not just a grep |
| Manual repro (before fix) | `grep -c "infrastructure.llm.factory\|FallbackProvider" data/logs/collector.log` | `0` (confirms the bug is present) |
| Manual repro (after fix) | `python scripts/run_collector.py --dry-run --sources medicalxpress --quiet 2>&1 \| grep -c "FallbackProvider\|Configuring.*Provider"` | non-zero (confirms messages now reach console) |

## Scope

**In scope**:
- `news_collector/infrastructure/llm/factory.py` — logger definition + all 10 `logger.info`/`logger.warning` call sites (format-string conversion).

**Out of scope** (do NOT touch, even though it looks related):
- `apps/refinery/published_content.py` — has the same `import logging; logger = logging.getLogger(...)` pattern (found during the same audit) but was not verified to have the same practical impact; investigate separately if desired, not part of this plan.
- Any `scripts/*.py` file using stdlib `logging` (`verify_fix.py`, `sync_lockfiles.py`, etc.) — these are standalone CLI tools with their own intentional, separate logging setup, not part of the shared pipeline log.
- `nvidia_provider.py`, `gemini_provider.py`, `provider.py` (Ollama) — already correctly wired to `get_logger()`; not touched.
- Any behavior change to `FallbackProvider`'s actual fallback logic — this plan only changes where its existing messages go, not what triggers them or what they say (beyond the mechanical `%s`→`{}` conversion).

## Git workflow

- Branch: `advisor/055-bridge-factory-logging`.
- Single commit is fine given the size of this change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Swap the logger

Replace `news_collector/infrastructure/llm/factory.py:3,15`:

```python
import logging
...
logger = logging.getLogger("news_collector.infrastructure.llm.factory")
```

with:

```python
from news_collector.utils.logger import get_logger
...
logger = get_logger().create_module_logger("infrastructure.llm.factory")
```

Remove the now-unused `import logging` only if nothing else in the file uses the stdlib module directly (check with `grep -n "logging\." news_collector/infrastructure/llm/factory.py` after this change — expect no matches outside the removed import).

### Step 2: Convert every call site from `%`-style to `{}`-style

Convert all 10 call sites. Each conversion is mechanical — replace `%s`/`%d` with `{}` in the message string; the positional arguments themselves don't change:

1. Line ~80-83: `"Skipping degraded provider %s during generate_sync"` → `"Skipping degraded provider {} during generate_sync"`
2. Line ~109-113: `"FallbackProvider attempting generate_sync with %s (timeout=%s)..."` → `"FallbackProvider attempting generate_sync with {} (timeout={})..."`
3. Line ~148-152: `"Provider %s failed during generate_sync: %s. Proceeding to fallback..."` → `"Provider {} failed during generate_sync: {}. Proceeding to fallback..."`
4. Line ~170-174: same as #1, `_async` variant
5. Line ~197-201: same as #2, `_async` variant
6. Line ~212-216: same as #3, `_async` variant
7. Line ~280-284: `"Configuring NvidiaProvider with model %s (max_tokens=%s)"` → `{}`/`{}`
8. Line ~314: `"Configuring GeminiProvider with model %s"` → `{}`
9. Line ~335: `"Configuring OllamaProvider with model %s"` → `{}`
10. Line ~347-350: `"Returning FallbackProvider with chain: %s"` → `{}`

**Verify**: `python -m pytest tests/unit/utils/test_logger_style.py -v` → all pass. This is the authoritative check — `test_no_percent_style_loguru_placeholders` fails with the exact file/line/placeholder if any `%s`/`%d` was missed, and `test_no_unbalanced_braces_in_loguru_messages` fails if a conversion introduced an unbalanced `{`/`}`; both only started scanning `factory.py` as of Step 1 (see "Why this matters"). Treat a plain `grep -n '%s\|%d' news_collector/infrastructure/llm/factory.py` (expect no matches) as a quick sanity check while editing, not a substitute for the pytest run.

### Step 3: Confirm messages reach both sinks

```
python scripts/run_collector.py --dry-run --sources medicalxpress --quiet 2>&1 | grep -E "FallbackProvider|Configuring (Nvidia|Gemini|Ollama)Provider|Returning FallbackProvider"
```

**Verify**: at least the "Configuring NvidiaProvider..." / "Configuring OllamaProvider..." / "Returning FallbackProvider with chain: [...]" lines appear in console output (these fire unconditionally during `get_provider()`, unlike the skip/fallback messages which only fire under specific runtime conditions). Then confirm the file sink too: `tail -50 data/logs/collector.log | grep -c "infrastructure.llm.factory"` → non-zero.

## Test plan

- No new automated test required — this is a logging-channel change with no branching logic to unit test. The manual verification in Step 3 is the regression guard (rerun it after any future change to this file).
- If a future reviewer wants an automated check, a smoke test could assert that `get_provider()` triggers at least one loguru-captured log record (via loguru's own `logger.add(callback)` sink pattern in a test) — optional, not required for this plan's done criteria.

## Done criteria

- [ ] `make lint` exits 0
- [ ] `make type` exits 0
- [ ] `make test` exits 0 (includes `tests/unit/utils/test_logger_style.py`, now covering `factory.py`)
- [ ] `python -m pytest tests/unit/utils/test_logger_style.py -v` passes explicitly (belt-and-suspenders on top of `make test`)
- [ ] `grep -n "import logging" news_collector/infrastructure/llm/factory.py` returns no matches
- [ ] Step 3's manual verification shows `FallbackProvider`/`Configuring...Provider` messages in both console and `data/logs/collector.log`
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 055 updated

## STOP conditions

- Any call site's message text changed meaning during the `%s`→`{}` conversion (e.g. an argument got dropped or reordered) — compare each converted line against the "Current state" excerpts character-by-character before committing.
- `make test` fails on a test that asserts specific log message text from this file (e.g. via `caplog` matching a `%s`-formatted string) — if found, update that test's expected string to the `{}`-style equivalent rather than reverting the format-string change, and note it in the commit message.
- Any step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If `apps/refinery/published_content.py` is later found to have the same practical impact (its own log messages silently dropped), it should get the identical fix — same pattern, separate plan/PR.
- A reviewer should scrutinize: that no call site's argument count/order shifted during the mechanical conversion (Step 2's 10 sites are individually small but easy to fat-finger under batch editing).
