# ADR-0009: Multi-provider LLM chain with classified failures

**Date**: 2026-09-19
**Status**: Accepted
**Deciders**: Engineering team

---

## Context

The chain was NVIDIA NIM → Gemini (never configured) → local Ollama. The
2026-09-18 pipeline audit measured ~10 % failed NIM calls (503, 60 s read
timeouts; zero 429), latency p50 ≈ 21 s / p90 ≈ 62 s, and one blank HTTP 200
that left an article with an empty excerpt and blocked its publication. NIM
was effectively a single point of failure; every failure was an untyped
`except Exception`, so nothing could be learned from them.

## Decision

1. **`OpenAICompatProvider`** — a thin subclass of `NvidiaProvider` (NIM is
   OpenAI-compatible, so retries, JSON extraction, rate limiting and the
   degradation window are reused). Any OpenAI-compatible service (Groq,
   OpenRouter `:free`, Cloudflare Workers AI, a self-hosted
   gateway such as freellmapi) is one `[[llm_endpoints]]` entry. Extracting a
   shared base class from `NvidiaProvider` is deferred until a second
   protocol needs it (avoids a 700-line refactor with no behavior change).
2. **Secrets by reference** — endpoints name a variable (process environment first, then the repo `.env`, which config loading reads without exporting)
   (`api_key_env`); an unset variable skips that endpoint with a warning.
3. **Explicit failure taxonomy** (`failure_kinds.FailureKind`) drives policy:
   `AUTH` disables the provider for 1 h (logged once, then retried so a key
   rotation heals without a restart in long-lived services),
   `RATE_LIMITED` cools it down honoring `Retry-After`, blank/invalid-JSON
   responses fail over, `CLIENT_ERROR` is not counted against provider health.
   The last provider keeps the historical semantics (result returned as-is,
   error propagated).
4. **Observability first** — every attempt emits a structured `llm.attempt`
   event (provider, model, purpose, kind, latency, failover index; skipped
   providers emit a zero-latency `degraded_skip`) and is
   offered to pluggable sinks (`attempts.register_attempt_sink`), which are
   fail-open. `LLMMetricsStore` (SQLite, `data/metrics/<env>/llm_metrics.db`,
   90-day retention, disabled with `NOTICIENCIAS_LLM_METRICS=0`) persists them
   and `make llm-report` / `scripts/llm_health_report.py` summarizes per
   provider: success %, p50/p95, failure kinds, blank-response rate, skips and
   *saves* (calls rescued after another provider failed). `--probe` performs a
   live health check of each provider.
5. **Failover timeout stays at 60 s** for non-final providers. Measured p90
   is 62 s; a 30 s cap would divert ~35 % of calls to slow local Ollama.
   Fast failover on outages is handled by the degradation window instead.
6. **Groq is active by default** in `config.toml` (validated 2026-09-19:
   `openai/gpt-oss-120b`, JSON mode, Spanish, p50 ≈ 2 s vs NIM 4–21 s; NVIDIA
   forced to fail → served by Groq, skips and saves recorded). Without
   `GROQ_API_KEY` (e.g. CI, which also has no NVIDIA/Gemini keys) the endpoint
   is skipped with a single warning, so behavior there is unchanged.

7. **OpenRouter free route** (`nvidia/nemotron-3-super-120b-a12b:free`, same
   model as the primary on another host). The schema enforces the `:free`
   suffix for `openrouter.ai` endpoints because the account has purchased
   credit before (`is_free_tier=false`): a paid id would silently spend it.
   Gateways answer HTTP 200 with `{"error": {"code": 503}}`; that body is now
   raised as an HTTP error with the embedded status (retry/failover/cooldown
   apply) instead of being read as blank text. Degenerate JSON such as
   `{"": ""}` counts as an empty response.
8. **Cerebras is not used.** Its official docs state there is no permanently
   free tier: the Free Trial is $5 of credit that expires after 30 days and
   needs a verified payment method (an unfunded key answers 402
   `payment_required`). GitHub Models is retiring (410 brownout) and Gemini uses
   the native provider (`[gemini]`, flat alias `GEMINI_API_KEY`), not an
   OpenAI-compat entry. Verify any "free" provider against its own docs and a
   real call before adding it (freellmapi's catalog lists it, but that does not
   make it free for a continuous workload).

9. **Call budget (`generate_async(budget=...)`).** The CognitiveScorer wrapped
   the whole chain in one `asyncio.wait_for`; a slow first provider consumed it
   and cancelled the call before failover was ever tried (every scoring batch
   fell back to heuristics). With a budget each non-final attempt is capped at
   `MAX_ATTEMPT_S` (25 s, really cancelled) and the last provider gets the
   remainder. A first version used 60 % of the time left; measured on a real run
   that gave 24/9.6/3.8/1.5 s, starving every fallback, so it is a fixed cap.
10. **Per-purpose order (`[llm.purpose_chains]`).** Measured on a real 20-item
    scoring batch (2026-09-19): groq 6 s, openrouter 18 s, gemini 48 s, nvidia
    53 s, cloudflare 67 s. `scoring` (one batch per cycle, under a deadline)
    goes groq-first. `prescoring` is NOT groq-first: ~20 back-to-back calls
    exceed Groq's ~8000 tokens/min free cap. Editing keeps NVIDIA first.
11. **Per-provider circuit breakers.** The breaker was a process-wide singleton:
    Groq's 429s opened it for every provider, so all fallbacks failed with the
    first (observed: every provider `rate_limited`, LLM unusable for the cycle).
    `LLMRateLimiter.breaker_for(key)` gives each provider/endpoint its own.
    Endpoints fail fast on 429 (no sleeping through `Retry-After`; the chain
    fails over and cools the provider down) and default to 2 attempts.
12. **Metrics record service time.** `latency_ms` excludes the time spent waiting
    for a limiter slot (`queue_wait_ms` is stored separately); before, prescoring
    showed a 171 s median that was mostly queueing.

13. **Short rate-limit wait (budgeted async calls only).** A 20-item scoring batch
    is ~5000 tokens and Groq's free cap (8000/min) refills continuously (~25 s to
    free that much). When a provider answers 429 with `Retry-After` <= 30 s and
    the wait fits the caller's budget, the chain waits and retries that provider
    once (no cooldown) instead of failing over to a provider that needs 50 s+.
    Measured: 429 -> wait 14-18 s -> success in ~5 s. With ~4 batches per cycle
    (~20k tokens/min) the free cap is still a hard ceiling; some batches still
    fall back to heuristics.

14. **Token diet for scoring.** Output (mostly gpt-oss reasoning + per-item
    justification text) dominates scoring cost. The batch prompt no longer asks
    for per-item `reasoning` (nothing reads it) and the Groq endpoint sets
    `extra_body = { reasoning_effort = "low" }`. Measured: 5106 -> 2817 tokens
    for a 20-item batch (real scorer: 3758) with score differences inside the
    model's own run-to-run noise. Shortening summaries to 300 chars was rejected
    (correlations fell to ~0.4).

15. **Per-run LLM health report.** Prescoring and scoring degrade to heuristics
    silently when the chain fails. Each stage now records per-article outcomes
    (`observability/llm_run_stats`) and every run ends with a report
    (`observability/llm_run_report`): items done by LLM / cache / heuristic (with
    reason), per-provider results for *this* run (`llm_metrics.db`, filtered by
    `run_id`), a `llm.run.degraded` warning when a stage exceeds
    `[llm_health] warn_heuristic_ratio`, and `data/exports/llm_run_report.json`.
    Runs with no LLM activity (CI) never alert. First real run: 85 % of scoring
    items fell back, 307 of 314 as `llm_unavailable` (one failed chunk marks the
    LLM unhealthy for the rest of the cycle).

16. **Scorer failure cascade and cycle budget.** The first real report showed
    307 of 314 scoring items skipped: one failed chunk marked the LLM unhealthy
    for the whole cycle, and a hard-coded 200 s budget ended LLM use after ~4
    chunks of a 370-item cycle. Now 2 consecutive chunk failures disable it (a
    success resets the streak), the budget is `[scoring] llm_cycle_budget_seconds`
    (600) and unavailability reasons are reported separately. Measured on the
    same DB copy: LLM-scored 15 % -> 60 % (+15 % cached).

## Consequences

- Free-tier models can be weaker in Spanish editorial tasks: order the chain
  per measured results (`purpose` labels every call) and keep NVIDIA first.
- Free tiers carry provider terms/privacy caveats; the content processed is
  public news text.
- Adaptive re-ordering from metrics is intentionally out of scope.
