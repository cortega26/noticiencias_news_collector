# TODO: test-suite audit and hardening

- [x] Phase 0: audit tool, `make test-audit`, baseline report
- [x] Phase 1a: delete `tests/spikes`, `tests/legacy`, `tests/verify_*.py`, `tests/debug_*.py` (#296; evidence in the PR: 0 repo imports, coverage of real code unchanged at 17 190 lines, spike docs annotated)
- [x] Phase 1b: delete 26 orphan one-off scripts (no reference anywhere but archived plans/inventory, untouched since Feb-Jun, 0 % coverage). KEPT pending owner confirmation: `audit_pipeline` (composes the live source-reliability sweep with `audit_sources`; restored after review), recent tools (`audit_published_categories`, `bench_qwen35_json`, `generate_admin_openapi_snapshot`, `open_pr`, `reset_canary_sources`, `verify_canary_a_vs_b`, `verify_prompt`, `debug_proxy`, `profile_pipeline`), `migrate_metrics_db`, `weekly_quality_report`, `generate_production_report`
- [ ] Phase 1c: review skipped/`*_fix` tests
- [x] Phase 2a: `noticiencias/config_manager.py` 50 % -> 94 % (`tests/unit/config/test_config_manager_io.py`, real temp files, no mocks). `requests_client.py` was already 96 % (the audit XML was stale).
- [ ] Phase 2: gaps (requests_client, llm/health, auditor, router, basic_scorer, config_manager, CI scripts); widen --cov; re-record baseline
- [x] Phase 3a: mutation testing on 5 critical modules (`make mutation`, score script + floors, weekly workflow); `admission.py` 82 % -> 100 %
- [x] Phase 3b-1: `failure_kinds` 81 -> 91 %, `url_canonicalizer` 61 -> 85 % (remaining survivors are equivalent/dead code)
- [ ] Phase 3b-2: kill survivors in `llm_run_report` (67 %) and `grounding` (81 %); widen scope (coordinator, factory, rate_limiter, readability, uncertainty)
- [ ] Phase 3c: assertion-less/mock-heavy tests; hypothesis invariants (`check_grounding`, `evaluate_admission`, `redact_secrets`)
- [x] Phase 4a: removed unused `nltk`/`textblob` (+ `regex`, `tqdm`, `defusedxml`): retires the NLTK CVE exception that expired 2026-09-30; suite verified in a venv built strictly from the new lock
- [x] Phase 4b-1: group "web/http/validation" (starlette 1.6, pydantic 2.13.5 + core, anyio, urllib3 2.8, certifi, idna, charset-normalizer, typing-extensions, annotated-types, click) via new `sync_lockfiles.py --upgrade-package`
- [x] Phase 4b-2: group "data/ML" (alembic 1.20, sqlalchemy 2.0.54, numpy 2.5.3, scikit-learn 1.9.1, scipy 1.18.1, joblib, threadpoolctl, greenlet, mako, orjson; new transitive cloudpickle + narwhals)
- [ ] Phase 4b-3..: remaining groups (scraping: playwright/scrapling/curl-cffi/bs4/lxml/feedparser; tooling: ruff/mypy/coverage/hypothesis/pytest plugins)
- [ ] Phase 5: CI guardrails + docs/AGENTS.md test-quality rules
