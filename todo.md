# Todo — Migrate Nvidia NIM model to Qwen3-Next-80B-A3B-Instruct

- [ ] Modify `config.toml` to update default model setting to `qwen/qwen3-next-80b-a3b-instruct`
- [ ] Modify `noticiencias/config_schema.py` to update schema defaults and descriptions
- [ ] Modify `docs/config_fields.md` to update generated documentation
- [ ] Update LLM infrastructure defaults:
  - [ ] Modify `news_collector/infrastructure/llm/nvidia_provider.py`
  - [ ] Modify `news_collector/infrastructure/llm/health.py`
  - [ ] Modify `news_collector/infrastructure/llm/factory.py`
- [ ] Update Streamlit admin panel UI defaults in `apps/refinery/admin_panel.py`
- [ ] Update unit tests in `tests/test_nvidia_routing_fix.py`
- [ ] Verify using automated tests (`make test`)
- [ ] Verify using manual/dry-run run of the collector (`python scripts/run_collector.py --dry-run`)
