# TODO: test-suite audit and hardening

- [x] Phase 0: audit tool, `make test-audit`, baseline report
- [x] Phase 1a: delete `tests/spikes`, `tests/legacy`, `tests/verify_*.py`, `tests/debug_*.py` (#296; evidence in the PR: 0 repo imports, coverage of real code unchanged at 17 190 lines, spike docs annotated)
- [x] Phase 1b: delete 26 orphan one-off scripts (no reference anywhere but archived plans/inventory, untouched since Feb-Jun, 0 % coverage). KEPT pending owner confirmation: `audit_pipeline` (composes the live source-reliability sweep with `audit_sources`; restored after review), recent tools (`audit_published_categories`, `bench_qwen35_json`, `generate_admin_openapi_snapshot`, `open_pr`, `reset_canary_sources`, `verify_canary_a_vs_b`, `verify_prompt`, `debug_proxy`, `profile_pipeline`), `migrate_metrics_db`, `weekly_quality_report`, `generate_production_report`
- [ ] Phase 1c: review skipped/`*_fix` tests
- [x] Phase 2a: `noticiencias/config_manager.py` 50 % -> 94 % (`tests/unit/config/test_config_manager_io.py`, real temp files, no mocks). `requests_client.py` was already 96 % (the audit XML was stale).
- [x] Phase 2b: `--cov` widened to `noticiencias` (legacy `gui_config.py` omitted like `admin_panel.py`); `.coverage-baseline` re-recorded 85.20/73.43 -> 91.25 line / 80.92 branch (measured 91.75/81.92 minus a 0.5/1.0 noise margin), so the ratchet floor rises ~6 points
- [ ] Phase 2c: remaining gaps by risk: `llm/health`, `auditor`, `enrichment/router`, `basic_scorer`, `published_content`, `html_collector`, CI scripts (`sync_lockfiles`, `bump_version`, `validate_plans_ledger`, `quality_gate_refresh`)
- [x] Phase 3a: mutation testing on 5 critical modules (`make mutation`, score script + floors, weekly workflow); `admission.py` 82 % -> 100 %
- [x] Phase 3b-1: `failure_kinds` 81 -> 91 %, `url_canonicalizer` 61 -> 85 % (remaining survivors are equivalent/dead code)
- [ ] Phase 3b-2: kill survivors in `llm_run_report` (67 %) and `grounding` (81 %); widen scope (coordinator, factory, rate_limiter, readability, uncertainty)
- [ ] Phase 3c: assertion-less/mock-heavy tests; hypothesis invariants (`check_grounding`, `evaluate_admission`, `redact_secrets`)
- [x] Phase 4a: removed unused `nltk`/`textblob` (+ `regex`, `tqdm`, `defusedxml`): retires the NLTK CVE exception that expired 2026-09-30; suite verified in a venv built strictly from the new lock
- [x] Phase 4b-1: group "web/http/validation" (starlette 1.6, pydantic 2.13.5 + core, anyio, urllib3 2.8, certifi, idna, charset-normalizer, typing-extensions, annotated-types, click) via new `sync_lockfiles.py --upgrade-package`
- [x] Phase 4b-2: group "data/ML" (alembic 1.20, sqlalchemy 2.0.54, numpy 2.5.3, scikit-learn 1.9.1, scipy 1.18.1, joblib, threadpoolctl, greenlet, mako, orjson; new transitive cloudpickle + narwhals)
- [x] Phase 4b-3: group "scraping" (playwright/patchright 1.63, curl-cffi 0.16, beautifulsoup4 4.15, lxml 6.1.3, feedparser 6.0.14, cssselect, cffi, apify-fingerprint-datapoints); rich/pygments/markdown-it-py/mdurl/sgmllib3k leave the runtime lock, feedparser-sgmllib joins
- [x] Phase 4b-4: tooling locked in the security lock (bandit 1.9.4, hypothesis 6.168.0); `sync_lockfiles --upgrade-package` now only touches locks that already pin the package
- [ ] Phase 4c (owner decision): tools not in any lock (ruff 0.16, mypy 2.3.1, coverage, black, isort 9 major, pytest-randomly 5 major, semgrep 1.177 blocked by its rich/protobuf pins) are installed by `make bootstrap` outside the locks
- [x] Phase 5: weekly `test-health-weekly.yml` (clock +14 d: time bombs and allowlist expiries early warning), `docs/AGENTS.md` §4.1 test-usefulness criteria; ratchet baseline and mutation floors already enforced (2b, 3a)
