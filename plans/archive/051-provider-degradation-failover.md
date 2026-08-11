# Plan 051: LLM provider degradation failover

> **Executor instructions**: Fix for chronic NVIDIA NIM read timeouts
> (`integrate.api.nvidia.com`, read timeout=60, attempts 1/2 and 2/2).
> Today's run (`data/logs/collector.log`, 2026-08-07 11:49-11:57) shows 8
> ERROR lines — all `Sync NVIDIA NIM error (attempt 1/2)` / `(attempt 2/2)`
> — plus 25 WARNINGs. The same pattern is chronic: 11–90 nvidia timeouts
> per log file since 2026-08-02.
>
> Root cause analysis (completed in-session):
> 1. `FallbackProvider` (factory.py:70-73) forces a 60s timeout on every
>    provider except the last in the chain, so each NVIDIA call burns
>    up to 60s × 2 attempts = 120s before failover to Gemini/Ollama.
> 2. Every failed attempt logs `logger.error` because `log_errors_as_warning`
>    defaults to False and the callers (PreScorer, Council, Classifier) never
>    pass it. Only the auditor passes it (`log_errors_as_warning=self.optional`).
> 3. `CircuitBreaker.record_error()` (rate_limiter.py:123-125) is a no-op —
>    network timeouts NEVER trip any degradation; only 429s count. There is
>    no mechanism to remember that NVIDIA is down between calls, so every
>    article re-burns the full 2×60s before falling back.
> 4. Result: repeated ERROR throughput + up to 120s of dead wait per article
>    that needs the LLM while NVIDIA NIM is degraded.
>
> Drift check: `git status --short` and `git diff --stat HEAD` must show
> only plan files + the intended code/test/config changes.
>
> Must finish with `make lint && make type && make test` (+
> `make config-docs-check` since `config_schema.py` changes) per
> `docs/AGENTS.md` §10.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH (infrastructure/LLM provider — shared path for scoring,
  editorial, and enrichment)
- **Depends on**: none
- **Category**: bugfix (log noise + latency + provider failover robustness)
- **Planned at**: backend, 2026-08-07

## Why this matters

NVIDIA NIM has been intermittently degraded for days (read timeouts are
chronic across multiple log rotations). The collector still works because
`FallbackProvider` eventually fails over to Gemini/Ollama — but it pays for
that resilience with 8 ERRORs and ~120s of dead wait per LLM-dependent
article, every single run. The user's standing requirement is that
WARNINGs and ERRORs in the logs be reduced to genuinely meaningful events,
not routine environmental noise. This plan makes degradation a first-class,
remembered state: once NVIDIA shows N consecutive network failures it is
marked degraded for a cooldown window, skipped directly by the fallback
chain, and only probed again via a cheap health check. While fallback is
in control, provider errors are logged as WARNINGs instead of ERRORs.

## Current state

- `FallbackProvider.generate_sync` iterates providers sequentially
  (factory.py:55-139): NVIDIA → Gemini → Ollama (when configured), forcing
  timeout=60 on non-last providers.
- `NvidiaProvider.generate_sync` (nvidia_provider.py:386-478) retries up to
  `max_retries` times with exponential backoff, logging each failure at
  ERROR level unless `log_errors_as_warning` is set.
- `LLMRateLimiter` circuit breaker (rate_limiter.py:73-131) only reacts to
  429s (`record_rate_limit`); `record_error` is a no-op. It is a global
  breaker shared by all providers, so it cannot be used for per-provider
  degradation (opening it would also block Gemini/Ollama).
