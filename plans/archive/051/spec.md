# Spec: Plan 051 — LLM provider degradation failover

## Goals

1. A provider that fails N consecutive LLM calls (network errors/timeouts/
   5xx/429) becomes **degraded** for a configurable cooldown window,
   independent of the other providers in the chain.
2. While degraded, the fallback chain **skips** the provider directly —
   no request is attempted, no dead 60s×2 wait per article.
3. After the cooldown elapses, the provider is probed with a cheap
   `check_health()` (5s); success re-activates it, failure keeps it degraded.
4. Provider errors logged while the fallback chain is in control become
   **WARNINGs**, not ERRORs — the ERROR level is reserved for the whole
   chain failing.
5. Everything is configurable under `[nvidia]` with sane defaults, and
   documented in `docs/config_fields.md`.

Acceptance criteria:
- After N consecutive LLM call failures, `NvidiaProvider.is_degraded()` is
  True and `generate_sync`/`generate_async` raise a fast fail without
  hitting the network or sleeping.
- `FallbackProvider` skips a degraded provider and logs a single WARNING.
- Once the cooldown passes, a successful health probe restores the provider
  and it is attempted again on the next call.
- No ERROR is logged for a provider failure while a later provider in the
  chain is configured and reachable.

## Design decisions

- **Per-provider state, not global circuit breaker.** `LLMRateLimiter`'s
  breaker is process-global and shared by all providers; opening it would
  stall Gemini/Ollama too. Degradation must live on the provider instance.
- **Degradation is remembered across calls.** Unlike the (no-op)
  `record_error`, failed calls increment a consecutive-failure counter that
  persists on the provider until cooldown or recovery.
- **Skip, don't fail.** A degraded provider is skipped by the fallback
  chain before attempting, so no request is emitted and no backoff sleep
  burns wall-clock time.
- **Health probe decides recovery.** `check_health()` already exists
  (nvidia_provider.py:480-495); it is cheap (5s, `/models`). After the
  cooldown, exactly one probe decides whether to re-arm or keep degraded.

## Implementation details

### A. Config schema — `noticiencias/config_schema.py` (`NvidiaConfig`)

Add to `NvidiaConfig` (after `max_tokens`):

```python
degraded_failure_threshold: PositiveInt = Field(
    default=2,
    description=(
        "Consecutive LLM failures before the NVIDIA provider is marked "
        "degraded and skipped by the fallback chain."
    ),
)
degraded_cooldown_seconds: PositiveFloat = Field(
    default=300.0,
    description=(
        "Seconds the provider stays degraded before a health probe "
        "is allowed to re-arm it."
    ),
)
degraded_probe_timeout_seconds: PositiveFloat = Field(
    default=5.0,
    description="Timeout used for the health probe that re-arms a degraded provider.",
)
```

### B. Runtime config — `config.toml` `[nvidia]`

```toml
degraded_failure_threshold = 2
degraded_cooldown_seconds = 300.0
degraded_probe_timeout_seconds = 5.0
```

### C. `NvidiaProvider` degradation state

Add state + helpers to `NvidiaProvider.__init__`:

```python
self.degraded_failure_threshold = degraded_failure_threshold
self.degraded_cooldown_seconds = degraded_cooldown_seconds
self.degraded_probe_timeout_seconds = degraded_probe_timeout_seconds
self._consecutive_failures = 0
self._degraded_until: float = 0.0
self._degraded_announced = False
```

Public methods:

```python
def is_degraded(self) -> bool
def _record_failure(self) -> None:     # increments; trips degraded state
def _record_success(self) -> None:     # resets consecutive failures
def maybe_probe(self, now: float) -> None:  # re-arm if cooldown elapsed
```

- `is_degraded()`: returns True if `time.monotonic() < self._degraded_until`.
  If `_degraded_announced` is False, log a single `logger.warning("NVIDIA … "
  "marked degraded for ...s")` and set it.
- `_record_failure()`: increments `_consecutive_failures`; when it reaches
  `degraded_failure_threshold`, set `_degraded_until =
  time.monotonic() + cooldown`, log WARNING, reset counter. On initial arm,
  always call `maybe_probe` to decide recovery.
- `_record_success()`: reset `_consecutive_failures`.

In `generate_sync` (and `generate_async`): on a `requests.RequestException`
patch the error handling:

```python
except requests.RequestException as e:
    safe_msg = redact_message(str(e))
    is_rate_limit = self._is_429(e)
    self._record_failure()
    ...
    log_fn = logger.warning  # provider failures are WARNINGs while chain active
```

On success → `self._record_success()`.

### D. `FallbackProvider` skips degraded providers

In `factory.py` both `generate_sync` and `generate_async`, at the top of the
provider loop:

```python
if getattr(provider, "is_degraded", None) and provider.is_degraded():
    logger.warning(
        "Skipping degraded provider %s during generate_...",
        provider.__class__.__name__,
    )
    continue
```

After the loop (all actors failed), the final re-raise stays.

### E. Error re-lookup during chained fallback

When the first provider fails and the second succeeds, the chain logs the
failure via the `except` in each provider. Ensure the `logger.warning` path
is used when `log_errors_as_warning=True` is passed down by the caller (it
already is in `audiutor.py`). No caller changes required.

### F. Tests

New `tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py`:
- unit: after N consecutive timeouts, `is_degraded()` is True and
  `generate_sync` no longer issues HTTP calls (side-effect free skip).
- integration: cooldown expiry + healthy probe re-arms provider.
- regression: existing routing/rate-limiter tests still pass with new
  constructor args defaulted.

Existing test in `tests/test_nvidia_routing_fix.py` and
`tests/infrastructure/llm/test_nvidia_provider_coverage.py` must keep
passing; verify no constructor break.

## Files changed

- `noticiencias/config_schema.py`
- `config.toml`
- `news_collector/infrastructure/llm/nvidia_provider.py`
- `news_collector/infrastructure/llm/factory.py`
- `docs/config_fields.md` (regenerated by `make config-docs-check`)
- `tests/unit/infrastructure/llm/test_nvidia_provider_degradation.py`
- `tests/infrastructure/llm/test_nvidia_provider_coverage.py` (maybe)

## Verification

```bash
make lint
make type
make test
make test-boundaries      # infrastructure/LLM boundary touched
make config-docs-check    # config schema change
```

- New degradation unit tests above.
- Regression: `make test-contracts` (coverage gate 77.56% vs 80% is the
  pre-existing unrelated failure noted in plan 050).
- e2e smoke (manual): run one collector cycle with NVIDIA temporarily
  unreachable (mock/`patch` at request layer or point `base_url` at a
  closed port) and confirm the log shows a single WARNING for degradation
  plus "skipping degraded provider", and NO ERROR lines while Gemini/Ollama
  succeed.
- `git diff --stat` limited to intended files.
