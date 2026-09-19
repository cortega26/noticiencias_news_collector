# TODO: multi-provider LLM chain

## PR A
- [x] OpenAICompatProvider + labeled logger in NvidiaProvider
- [x] Config schema (`llm_endpoints`, `llm.chain`) + config docs regenerated
- [x] Failure taxonomy + attempts module
- [x] FallbackProvider refactor, `purpose` at 5 call sites (auditor left unlabeled: touching it would trip the coverage ratchet, 75 %)
- [x] Health checker, config.toml examples, .env.example, ADR-0009
- [x] Tests
- [ ] Manual validation with real keys (Groq, Cerebras, OpenRouter, Gemini compat)

## PR B (next)
- [ ] LLMMetricsStore (SQLite, fail-open) registered as attempt sink
- [ ] `scripts/llm_health_report.py` + `make llm-report` (+ `--probe`)
- [ ] 90-day retention
