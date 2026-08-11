# Plan 053: Harden the NVIDIA provider degradation mechanism before it ships

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Baseline note (read before the drift check)**: this plan patches code
> that, as of this writing, exists **only in the uncommitted working tree**
> as plan 051's implementation (`plans/051-provider-degradation-failover.md`,
> not yet committed). Before doing anything else, confirm those changes are
> still present:
> `git status --short news_collector/infrastructure/llm/factory.py news_collector/infrastructure/llm/nvidia_provider.py noticiencias/config_schema.py config.toml`
> must show all four as modified (`M`). If they show clean (no diff) or the
> file lacks `is_degraded`/`_record_failure`/`_fail_fast_if_degraded`, plan
> 051 was committed, reverted, or reworked since this plan was written —
> re-read `news_collector/infrastructure/llm/nvidia_provider.py` in full
> before proceeding and treat any mismatch with "Current state" below as a
> STOP condition.
>
> **Drift check (run after the baseline note above passes)**:
> `git diff --stat 9a1e4a8..HEAD -- news_collector/infrastructure/llm/ noticiencias/config_schema.py config.toml tests/unit/infrastructure/llm/`
> Expect no committed changes to these paths beyond `9a1e4a8` itself (plan
> 051's changes are uncommitted, so this should be empty — the real check is
> the `git status --short` above).

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED — shared LLM infrastructure path (scoring, editorial, enrichment all depend on it), but plan 051 is still uncommitted, so this is the cheapest point in its lifecycle to fix.
- **Depends on**: plan 051's uncommitted implementation must be present in the working tree (see baseline note). Not a dependency on a *merged* plan — a dependency on the *files*.
- **Category**: bug
- **Planned at**: commit `9a1e4a8`, 2026-08-07 (working tree also carries plan 051's uncommitted diff — see baseline note)

## Why this matters

Plan 051 added a per-provider degraded state to `NvidiaProvider` (consecutive-failure counter, cooldown window, half-open probe) so the collector stops burning ~120s of dead network wait per LLM call once NVIDIA NIM is known to be down. Two design gaps undercut that goal, both found by reading the actual uncommitted code (not the plan's own description of itself) and cross-checked against today's real production log (`data/logs/collector.2026-08-07_11-49-31_138988.log.gz`, isolated to the real collector process — PID 2215310, not the pytest workers sharing the same log file):

1. **The degraded state lives on the `NvidiaProvider` instance, not the process.** `get_provider()` (`factory.py`) constructs a fresh `NvidiaProvider` on every call with no caching. Six independent call sites each hold their own instance — `pre_scorer.py:42`, `cognitive_scorer.py:70`, `classifier.py:31`, `council.py:57`, `auditor.py:165`, `ai_editor.py:501` — so each of the six must independently rediscover degradation. A single shared, process-wide "NVIDIA is down" fact would let all six benefit from the first discovery instead of each paying its own ~120s tax.
2. **The failure counter is reset by any single success**, including a successful retry within an otherwise-failing call. Today's production log shows *why this is dangerous*: of 21 calls whose first attempt hit a NVIDIA read timeout, only 10 also failed their second attempt — 11 recovered on retry within the same hour. That is intermittent flakiness, not a hard outage. With today's config, `degraded_failure_threshold` (2) happens to equal every caller's effective `max_retries` (2 — `auditor.py:170` is the only caller that overrides it, from `[editorial_auditor].max_retries = 2` in `config.toml:525`, and that happens to match the factory default the other five callers use), so a single call whose *both* attempts fail is enough to trip degradation on its own. But nothing enforces that coupling. If `degraded_failure_threshold` is ever raised above the effective `max_retries` for any caller (a very plausible tuning move, to avoid flagging a single blip), degradation can only be reached by accumulating failures **across separate calls** — and a single intervening success (which, per the log, happens roughly half the time) resets that accumulation to zero. The provider could stay "not degraded" indefinitely while still timing out on every other call.

Fixing both now — while plan 051 is still uncommitted — is strictly cheaper than fixing them after merge and after other code has grown to depend on the current per-instance shape.

## Current state

Files and their role:

- `news_collector/infrastructure/llm/nvidia_provider.py` — owns `is_degraded()`, `maybe_attempt()`, `_fail_fast_if_degraded()`, `_record_failure()`, `_record_success()`, and the state they mutate (`self._consecutive_failures`, `self._degraded_until`, `self._degraded_announced`, `self._degradation_lock`), all set up in `__init__` (lines ~86-95).
- `news_collector/infrastructure/llm/factory.py` — `get_provider()` (lines 244-353) constructs a new `NvidiaProvider` per call, reading `degraded_failure_threshold`/`degraded_cooldown_seconds`/`degraded_probe_timeout_seconds` from `cfg.nvidia` (lines 275-296). `FallbackProvider._is_degraded()` (lines 18-27) and its use in `generate_sync`/`generate_async` are correct as-is and out of scope for this plan.
- `noticiencias/config_schema.py` — `NvidiaConfig` (around line 848) already carries `degraded_failure_threshold: PositiveInt = 2`, `degraded_cooldown_seconds: PositiveFloat = 300.0`, `degraded_probe_timeout_seconds: PositiveFloat = 5.0`.
- `tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py` — 19 tests, several of which poke instance attributes directly (`provider._degraded_until = ...`, `provider._degraded_announced`, `provider._consecutive_failures` via `_record_failure()`). These will need updating in lockstep with the state-ownership change (see Step 3).

Current degradation state, exactly as it exists in the working tree today (`nvidia_provider.py:86-95, 520-593`):

```python
        self._consecutive_failures = 0
        self._degraded_until: float = 0.0
        self._degraded_announced = False
        self._degradation_lock = threading.Lock()
    ...
    def is_degraded(self) -> bool:
        with self._degradation_lock:
            if self._degraded_until == 0.0:
                return False
            ...

    def _record_failure(self) -> None:
        with self._degradation_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.degraded_failure_threshold:
                self._degraded_until = time.monotonic() + self.degraded_cooldown_seconds
                ...
                self._consecutive_failures = 0

    def _record_success(self) -> None:
        with self._degradation_lock:
            self._consecutive_failures = 0
            if self._degraded_until != 0.0:
                self._degraded_until = 0.0
                ...
```

The six call sites, all identical in shape (`config=active_config`, no `max_retries` override except `auditor.py`):

```python
# news_collector/scoring/pre_scorer.py:42 (same shape in cognitive_scorer.py:70,
# classifier.py:31, council.py:57)
self.llm = get_provider(
    config=active_config,
    api_url=active_config.ollama.api_url,
    model=model,
)
```

```python
# news_collector/components/editorial/auditor.py:165-171 — the one caller
# that overrides max_retries
self.provider = get_provider(
    ...
    timeout=self.timeout_seconds,
    max_retries=self.max_retries,   # from [editorial_auditor].max_retries = 2
)
```

## Commands you will need

Per `docs/AGENTS.md` §10, `infrastructure/llm/` is a HIGH-risk boundary (orchestration/collector/storage/serving tier) — use the baseline + `make test-boundaries`.

| Purpose | Command | Expected on success |
|---|---|---|
| Lint | `make lint` | exit 0 |
| Types | `make type` | exit 0, no new mypy errors |
| Unit tests | `make test` | all pass |
| Boundary tests | `make test-boundaries` | all pass |
| Config docs | `make config-docs-check` | exit 0 (only if you add a new config field — see Step 1) |
| Targeted | `python -m pytest tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py -q` | all pass, including new tests from Step 3 |

## Scope

**In scope**:
- `news_collector/infrastructure/llm/nvidia_provider.py`
- `news_collector/infrastructure/llm/factory.py` — **narrowly**: only the `NvidiaProvider(...)` construction block inside `get_provider()` (~lines 285-297), to read and pass `degraded_window_size` (Step 1). Nothing else in this file changes.
- `noticiencias/config_schema.py` (one new field on `NvidiaConfig`)
- `config.toml` (mirror the new field under `[nvidia]`)
- `docs/config_fields.md` (mirror via `make config-docs-check`, do not hand-edit)
- `tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py`

**Out of scope** (do NOT touch, even though they look related):
- `news_collector/infrastructure/llm/factory.py`'s `FallbackProvider._is_degraded()` and the skip logic (lines ~18-27, ~79-84, ~169-174) — already work correctly against `provider.is_degraded()`; not touched by this plan. (Note: if plan 055 lands first or concurrently, it touches the same file's logger definition and ~10 message call sites, in a disjoint region from this plan's one-block edit — expect a neighbor diff, not a conflict, when rebasing either plan onto the other.)
- The six caller files (`pre_scorer.py`, `cognitive_scorer.py`, `classifier.py`, `council.py`, `auditor.py`, `ai_editor.py`) — they should not need to change; the shared-state fix is transparent to them (same `get_provider()` call shape).
- `gemini_provider.py`, `provider.py` (Ollama) — this plan is scoped to the NVIDIA provider only.
- The consecutive-vs-window semantics of `LLMRateLimiter`'s circuit breaker (`rate_limiter.py`) — separate mechanism (429-only), not touched by plan 051 or this plan.
- Plan 052 (reserved for the schneier.com 429 throttle, not yet written) — unrelated.

## Git workflow

- Branch: `advisor/053-nvidia-degradation-hardening` (repo convention: `advisor/NNN-slug`, seen in `plans/031`'s "Worker fetch-boundary" note and `plans/032`'s branch name).
- Commit per step.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add `degraded_window_size` config and switch failure tracking from strictly-consecutive to windowed

In `noticiencias/config_schema.py`, add a fourth field to `NvidiaConfig` alongside the three existing `degraded_*` fields (around line 866, after `degraded_probe_timeout_seconds`):

```python
    degraded_window_size: PositiveInt = Field(
        default=5,
        description=(
            "Number of most-recent LLM call outcomes to track when deciding "
            "whether to mark the NVIDIA provider degraded. A provider is "
            "marked degraded once `degraded_failure_threshold` failures "
            "appear within this window — not only on strictly consecutive "
            "failures."
        ),
    )
```

Mirror it in `config.toml`'s `[nvidia]` section, next to the other three `degraded_*` keys:
```toml
degraded_window_size = 5
```

In `news_collector/infrastructure/llm/nvidia_provider.py`, replace the plain
`int` counter with a bounded deque of recent outcomes. In `__init__`:
- Add `degraded_window_size: int = 5` to the constructor signature (after `degraded_probe_timeout_seconds`).
- Add `from collections import deque` to the imports.
- Replace `self._consecutive_failures = 0` with `self._recent_outcomes: "deque[bool]" = deque(maxlen=degraded_window_size)` (store `False` for a failure, `True` for a success).
- Store `self.degraded_window_size = degraded_window_size`.

Rewrite `_record_failure()` and `_record_success()`:

```python
    def _record_failure(self) -> None:
        with self._degradation_lock:
            self._recent_outcomes.append(False)
            failures = self._recent_outcomes.count(False)
            if failures >= self.degraded_failure_threshold:
                self._degraded_until = time.monotonic() + self.degraded_cooldown_seconds
                self._degraded_announced = False
                logger.warning(
                    "NVIDIA NIM marked degraded for {:.0f}s after {} failures "
                    "in the last {} attempts",
                    self.degraded_cooldown_seconds,
                    failures,
                    len(self._recent_outcomes),
                )
                self._recent_outcomes.clear()

    def _record_success(self) -> None:
        with self._degradation_lock:
            self._recent_outcomes.append(True)
            if self._degraded_until != 0.0:
                self._degraded_until = 0.0
                self._degraded_announced = False
                logger.warning("NVIDIA NIM recovered after a successful response")
```

Note the deliberate behavior change from plan 051's original: a single success **no longer erases prior failures outright** — it just becomes part of the rolling window. Only a full `_recent_outcomes.clear()` on tripping degradation, or the deque naturally aging old entries out past `maxlen`, removes old failures. This is the fix for gap 2 in "Why this matters."

Update `factory.py`'s `get_provider()` (lines ~275-297) to read and pass the new field:
```python
        use_degraded_window = getattr(nvidia_cfg, "degraded_window_size", 5)
        ...
        providers.append(
            NvidiaProvider(
                ...
                degraded_window_size=use_degraded_window,
            )
        )
```

**Verify**: `make config-docs-check` → exit 0, `docs/config_fields.md` gains a `nvidia.degraded_window_size` row automatically.

### Step 2: Share degradation state across all `NvidiaProvider` instances for the same endpoint

Add a module-level registry to `news_collector/infrastructure/llm/nvidia_provider.py`, above the `NvidiaProvider` class:

```python
class _DegradationState:
    """Shared degradation state for one (base_url, model) NVIDIA endpoint.

    Multiple NvidiaProvider instances constructed for the same endpoint
    (PreScorer, CognitiveScorer, Classifier, Council, Auditor, AIEditor each
    build their own via get_provider()) share one of these so degradation
    discovered by one caller is immediately visible to the others.
    """

    def __init__(self, window_size: int) -> None:
        self.lock = threading.Lock()
        self.recent_outcomes: "deque[bool]" = deque(maxlen=window_size)
        self.degraded_until: float = 0.0
        self.degraded_announced: bool = False


_DEGRADATION_REGISTRY: Dict[str, _DegradationState] = {}
_REGISTRY_LOCK = threading.Lock()


def _get_degradation_state(key: str, window_size: int) -> _DegradationState:
    with _REGISTRY_LOCK:
        state = _DEGRADATION_REGISTRY.get(key)
        if state is None:
            state = _DegradationState(window_size)
            _DEGRADATION_REGISTRY[key] = state
        return state
```

In `NvidiaProvider.__init__`, after `self.base_url` and `self.model` are set, replace the four `self._consecutive_failures` / `self._degraded_until` / `self._degraded_announced` / `self._degradation_lock` attributes with:

```python
        self._state = _get_degradation_state(
            f"{self.base_url}|{self.model}", degraded_window_size
        )
```

Rewrite `is_degraded()`, `maybe_attempt()`, `_record_failure()`, `_record_success()` to read/write `self._state.lock`, `self._state.recent_outcomes`, `self._state.degraded_until`, `self._state.degraded_announced` instead of the old `self._degradation_lock` / `self._consecutive_failures` / etc. The logic inside each method is otherwise unchanged from Step 1.

**Known limitation to document, not solve here**: if two `NvidiaProvider` instances for the same `(base_url, model)` are ever constructed with *different* `degraded_cooldown_seconds` or `degraded_window_size` (none of the six current callers do this — all read from the same global `cfg.nvidia`), the first instance constructed wins and later instances silently use its window size. Add a one-line comment on `_get_degradation_state` noting this.

**Verify**: `python -c "from news_collector.infrastructure.llm.nvidia_provider import NvidiaProvider; a = NvidiaProvider(api_key='x'); b = NvidiaProvider(api_key='x'); a._record_failure(); a._record_failure(); print(b.is_degraded())"` → prints `True` (proves state is shared across two independently-constructed instances for the same default `base_url`/`model`).

### Step 3: Update and extend the test file

`tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py` pokes instance state directly in several places (e.g. `provider._degraded_until = time.monotonic() - 1.0` in `test_cooldown_elapsed_healthy_probe_rearms`, `provider._degraded_announced` in `test_is_degraded_announces_once`). Update every such reference to go through `provider._state` instead (e.g. `provider._state.degraded_until = ...`).

Add an autouse fixture at the top of the test module to prevent state leaking between tests now that it's keyed by `(base_url, model)` and most tests use the same default `_provider()` values:

```python
@pytest.fixture(autouse=True)
def _clear_degradation_registry():
    from news_collector.infrastructure.llm.nvidia_provider import (
        _DEGRADATION_REGISTRY,
    )
    _DEGRADATION_REGISTRY.clear()
    yield
    _DEGRADATION_REGISTRY.clear()
```

Add new tests (new class `TestSharedDegradationState`):
- Two independently-constructed `NvidiaProvider` instances with the same `base_url`/`model` share degradation: failing on one is visible via `is_degraded()` on the other.
- Two instances with *different* `model` values do NOT share state.
- Windowed (non-consecutive) tripping: `degraded_failure_threshold=2`, `degraded_window_size=5` — record failure, success, failure → `is_degraded()` is `True` (this is the case that was impossible before Step 1; assert it explicitly as the regression test for gap 2).
- A success that doesn't immediately follow a failure still doesn't erase enough history to prevent tripping: failure, failure is still 2 outcomes in the last N — the existing `test_threshold_arms_degradation_after_n_failures` continues to pass unmodified only if it doesn't rely on `_consecutive_failures` internals; audit it and fix if it does.

**Verify**: `python -m pytest tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py -v` → all pass (19 existing + at least 3 new).

### Step 4: Full validation

Run the full command table from "Commands you will need". All must pass.

## Test plan

- Modified: `tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py` — attribute-path updates (Step 3) plus the new `TestSharedDegradationState` class (4 new cases: cross-instance sharing, isolation by model, windowed non-consecutive trip, existing consecutive case still works).
- Model the new tests after the existing `TestMaybeAttempt` / `TestGenerateSyncDegraded` classes in the same file — same `_provider()` helper, same `_FakeLimiter`/`_set_limiter` pattern for anything touching `generate_sync`.
- No new integration/e2e tests needed — this is an internal state-representation change behind the same public methods (`is_degraded`, `maybe_attempt`, `generate_sync`, `generate_async`) already covered by `tests/test_nvidia_routing_fix.py` and `FallbackProvider`'s own tests.

## Done criteria

- [ ] `make lint` exits 0
- [ ] `make type` exits 0
- [ ] `make test` exits 0
- [ ] `make test-boundaries` exits 0
- [ ] `make config-docs-check` exits 0, `docs/config_fields.md` shows `nvidia.degraded_window_size`
- [ ] `python -m pytest tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py -v` — all pass, including the 4 new shared-state/windowed tests
- [ ] `grep -n "_consecutive_failures" news_collector/infrastructure/llm/nvidia_provider.py` returns no matches (fully replaced by the windowed deque)
- [ ] Two `NvidiaProvider` instances built via separate `get_provider()` calls with identical config share degradation state (manual check from Step 2's verify command, or a test asserting it end-to-end through `get_provider()`)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 053 updated

## STOP conditions

- The baseline note's `git status --short` check shows plan 051's files are clean or missing the degradation methods — re-read the file fully before proceeding; do not assume this plan's "Current state" excerpts still match.
- `auditor.py`'s `max_retries` (from `[editorial_auditor].max_retries`) or any other caller's effective retry count changes independently of `degraded_failure_threshold` in a way that breaks an existing test's assumption — report the specific test and config values rather than adjusting the test to hide it.
- The shared-registry design (Step 2) causes a test in `tests/unit/infrastructure/llm/` outside the degradation test file to start failing due to cross-test state leakage — this means another test file constructs a real `NvidiaProvider` with default `base_url`/`model` and is sensitive to degradation state; add the same `_clear_degradation_registry` autouse fixture pattern there rather than removing the registry clear.
- Any step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If a seventh LLM-consuming component is added later, it gets shared degradation for free via `get_provider()` — no special wiring needed, as long as it doesn't pass a custom `base_url`/`model` combination that's meant to be tracked independently.
- If NVIDIA NIM's base URL or model changes at runtime (unlikely — both come from static config), the registry key changes and a fresh `_DegradationState` is created; old state for the previous key is abandoned in memory for the life of the process (not a practical leak — at most a handful of keys ever exist).
- A reviewer should scrutinize: the `_REGISTRY_LOCK` / per-state `lock` two-level locking in `_get_degradation_state` vs. `is_degraded()`/`_record_failure()` — confirm no deadlock path (they're never both held at once by design; `_get_degradation_state` releases `_REGISTRY_LOCK` before any caller touches `state.lock`).
- Plan 052 (schneier.com 429 throttle, not yet written) and this plan are independent; either can land first.
- **Land plan 055 (bridge `factory.py`'s logging to loguru) alongside or before this one.** `FallbackProvider`'s skip/attempt/fallback messages live in `factory.py`, which uses a disconnected stdlib logger — verified empirically on 2026-08-07 (`grep -c "infrastructure.llm.factory\|FallbackProvider" data/logs/collector.log` → `0` across a log containing runs that definitely exercised `FallbackProvider`). Without 055, this plan's own `is_degraded()`/`_record_failure()` WARNINGs (correctly logged from `nvidia_provider.py`, which is wired properly) will be visible, but `FallbackProvider`'s complementary "skipping degraded provider X" / "provider X failed, falling back" messages will not — an incomplete picture during incident debugging.
- **Known limitation, not addressed by this plan**: the degradation mechanism only reacts to hard failures (timeouts, 5xx, network errors) recorded via `_record_failure()`. It does not detect a provider that is *slow but technically successful*. Live evidence from the same 2026-08-07 session: two real `PreScorer` calls against NVIDIA completed successfully (no error, no warning) in 51s and 27s respectively, while NVIDIA's own lightweight health-check endpoint (`GET /models`, the same call `check_health()` makes) responded in 0.8s — a large gap between "provider reports healthy" and "provider actually responds quickly" that this plan's failure-counting logic cannot see, because a slow-but-successful call calls `_record_success()` just like a fast one. If this turns out to be a recurring pattern (worth checking after 053 and 055 both land and their logging makes it visible which provider actually served each call), it would need a separate plan — e.g. treating "success slower than N seconds" as a partial failure signal — not a mechanical extension of this one, since it's a product/design call about what counts as "degraded."
