# Spec: Migrate Nvidia NIM model to Qwen3-Next-80B-A3B-Instruct

## Goals
- Resolve the HTTP 410 Client Error (Gone) encountered when requesting the decommissioned model `qwen/qwen3-next-80b-a3b-thinking`.
- Systematically update all defaults, fallback code, configuration docs, and tests to use `qwen/qwen3-next-80b-a3b-instruct`.
- Maintain identical pipeline behavior and logic.

## Implementation Details

The model name `qwen/qwen3-next-80b-a3b-thinking` will be replaced with `qwen/qwen3-next-80b-a3b-instruct` in:
- `config.toml` (default config)
- `noticiencias/config_schema.py` (configuration schema defaults and descriptions)
- `docs/config_fields.md` (generated settings documentation)
- `news_collector/infrastructure/llm/nvidia_provider.py` (Nvidia LLM provider implementation)
- `news_collector/infrastructure/llm/health.py` (Nvidia LLM provider health check)
- `news_collector/infrastructure/llm/factory.py` (LLM provider factory)
- `apps/refinery/admin_panel.py` (Streamlit admin panel configuration presets)
- `tests/test_nvidia_routing_fix.py` (Routing test assertions)

## Verification
- Run `make test` to ensure no unit tests are broken.
- Execute the collector in dry-run mode (`python scripts/run_collector.py --dry-run`) to verify that the pipeline can run using the new model and successfully hit the chat completions API.
