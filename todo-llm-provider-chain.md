# TODO: multi-provider LLM chain

## PR A
- [x] OpenAICompatProvider + labeled logger in NvidiaProvider
- [x] Config schema (`llm_endpoints`, `llm.chain`) + config docs regenerated
- [x] Failure taxonomy + attempts module
- [x] FallbackProvider refactor, `purpose` at 5 call sites (auditor left unlabeled: touching it would trip the coverage ratchet, 75 %)
- [x] Health checker, config.toml examples, .env.example, ADR-0009
- [x] Tests
- [x] Manual validation with real key: Groq (e2e failover, metrics, report)
- [x] OpenRouter (:free), Cloudflare Workers AI and Gemini (native) validated with real keys
- [x] Cerebras dropped: no renewing free tier (ADR-0009 §8)

## PR B (next)
- [x] LLMMetricsStore (SQLite, fail-open) registered as attempt sink
- [x] `scripts/llm_health_report.py` + `make llm-report` (+ `--probe`)
- [x] 90-day retention
- [ ] Phase 2 (out of scope): adaptive chain re-ordering from the report
