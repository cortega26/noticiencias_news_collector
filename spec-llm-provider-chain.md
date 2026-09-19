# Spec: multi-provider LLM chain (PR A)

## Goals
- Remove NVIDIA NIM as a single point of failure with zero new services.
- Any OpenAI-compatible endpoint joins the chain via `[[llm_endpoints]]`.
- Failures are classified, logged as structured `llm.attempt` events and
  exposed to pluggable sinks so later iterations can learn from them.
- Delivered inactive: no endpoints configured => behavior unchanged.

## Design (see docs/adr/0009-multi-provider-llm-chain.md)
- `openai_compat_provider.OpenAICompatProvider` (subclass of `NvidiaProvider`).
- `failure_kinds` (`FailureKind`, `classify_exception`, `EmptyResponseError`).
- `attempts` (provider identity, process-wide disabled/cooldown registry,
  `AttemptRecord`, fail-open sinks).
- `factory.FallbackProvider` uses the above; `get_provider(purpose=...)`
  builds endpoints and applies `[llm] chain`.
- Config: `LLMEndpointConfig`, `LLMChainConfig`, `Config.llm_endpoints`, `Config.llm`.
- Health: `OpenAICompatHealthChecker`.

## Verification
- `tests/unit/infrastructure/llm/test_provider_chain.py`: classification,
  failover matrix (5xx, timeout, blank/`{}`, unknown), last-provider
  semantics, AUTH disable once process-wide, 429 cooldown with Retry-After,
  sinks fail-open, endpoint build/skip/inherit, chain order, schema rejects,
  health checker.
- `make lint && make type && make test && make test-boundaries && make test-contracts`.
- Manual (needs keys): set `GROQ_API_KEY` etc., add endpoints, invalidate the
  NVIDIA key, confirm failover + `llm.attempt` events.
