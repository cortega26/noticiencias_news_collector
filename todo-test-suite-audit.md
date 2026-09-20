# TODO: test-suite audit and hardening

- [x] Phase 0: audit tool, `make test-audit`, baseline report
- [x] Phase 1a: delete `tests/spikes`, `tests/legacy`, `tests/verify_*.py`, `tests/debug_*.py` (#296; evidence in the PR: 0 repo imports, coverage of real code unchanged at 17 190 lines, spike docs annotated)
- [ ] Phase 1b: delete orphan scripts (groups, with evidence)
- [ ] Phase 1c: review skipped/`*_fix` tests
- [ ] Phase 2: gaps (requests_client, llm/health, auditor, router, basic_scorer, config_manager, CI scripts); widen --cov; re-record baseline
- [ ] Phase 3: assertion-less/mock-heavy tests; mutmut on critical modules; hypothesis invariants
- [ ] Phase 4: dependency minors/patches by group
- [ ] Phase 5: CI guardrails + docs/AGENTS.md test-quality rules
