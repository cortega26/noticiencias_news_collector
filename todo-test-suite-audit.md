# TODO: test-suite audit and hardening

- [x] Phase 0: audit tool, `make test-audit`, baseline report
- [x] Phase 1a: delete `tests/spikes`, `tests/legacy`, `tests/verify_*.py`, `tests/debug_*.py` (#296; evidence in the PR: 0 repo imports, coverage of real code unchanged at 17 190 lines, spike docs annotated)
- [x] Phase 1b: delete 26 orphan one-off scripts (no reference anywhere but archived plans/inventory, untouched since Feb-Jun, 0 % coverage). KEPT pending owner confirmation: `audit_pipeline` (composes the live source-reliability sweep with `audit_sources`; restored after review), recent tools (`audit_published_categories`, `bench_qwen35_json`, `generate_admin_openapi_snapshot`, `open_pr`, `reset_canary_sources`, `verify_canary_a_vs_b`, `verify_prompt`, `debug_proxy`, `profile_pipeline`), `migrate_metrics_db`, `weekly_quality_report`, `generate_production_report`
- [ ] Phase 1c: review skipped/`*_fix` tests
- [x] Phase 2a: `noticiencias/config_manager.py` 50 % -> 94 % (`tests/unit/config/test_config_manager_io.py`, real temp files, no mocks). `requests_client.py` was already 96 % (the audit XML was stale).
- [ ] Phase 2: gaps (requests_client, llm/health, auditor, router, basic_scorer, config_manager, CI scripts); widen --cov; re-record baseline
- [ ] Phase 3: assertion-less/mock-heavy tests; mutmut on critical modules; hypothesis invariants
- [ ] Phase 4: dependency minors/patches by group
- [ ] Phase 5: CI guardrails + docs/AGENTS.md test-quality rules
