# Todo — Migrate Nvidia NIM model to Qwen3-Next-80B-A3B-Instruct

- [x] Modify `config.toml` to update default model setting to `qwen/qwen3-next-80b-a3b-instruct`
- [x] Modify `noticiencias/config_schema.py` to update schema defaults and descriptions
- [x] Modify `docs/config_fields.md` to update generated documentation
- [x] Update LLM infrastructure defaults:
  - [x] Modify `news_collector/infrastructure/llm/nvidia_provider.py`
  - [x] Modify `news_collector/infrastructure/llm/health.py`
  - [x] Modify `news_collector/infrastructure/llm/factory.py`
- [x] Update Streamlit admin panel UI defaults in `apps/refinery/admin_panel.py`
- [x] Update unit tests in `tests/test_nvidia_routing_fix.py`
- [x] Verify using automated tests (`make test`)
- [x] Verify using manual/dry-run run of the collector (`python scripts/run_collector.py --dry-run`)
