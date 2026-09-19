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
   the whole chain in one `asyncio.wait_for(40s)`; a slow first provider (NIM
   p90 ≈ 62 s) consumed it and cancelled the call before failover was ever
   tried (observed 2026-09-19: every scoring batch fell back to heuristics).
   With a budget, each non-final attempt is capped at 60 % of the time left
   (really cancelled) and the last provider gets the remainder, so failover fits
   inside the caller's deadline. Without a budget behavior is unchanged.

## Consequences

- Free-tier models can be weaker in Spanish editorial tasks: order the chain
  per measured results (`purpose` labels every call) and keep NVIDIA first.
- Free tiers carry provider terms/privacy caveats; the content processed is
  public news text.
- Adaptive re-ordering from metrics is intentionally out of scope.
