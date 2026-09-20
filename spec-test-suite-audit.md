# Spec: test-suite audit and hardening

## Goals
Know from data whether the test suite is useful, points at real code, covers what matters
(>=85 % lines) and really prevents regressions; then fix what the data shows, in small PRs.

## Design
- Phase 0 (this PR): `scripts/test_suite_audit.py` (pure analysis functions + CLI: coverage per
  file/package incl. `noticiencias` and `scripts`, critical gaps ranked by missing lines, tests
  touching no measured code via per-test coverage contexts, assertion-less tests, mock-heavy
  files) + `scripts/test_suite_audit.py` + `make test-audit` + baseline report in
  `docs/dev/TEST_SUITE_AUDIT.md`.
- Phase 1: delete obsolete tests/scripts in small PRs with evidence (0 references, no repo imports).
- Phase 2: close coverage gaps by risk; widen `--cov` to `noticiencias`; re-record the ratchet baseline.
- Phase 3: strengthen weak tests; mutation testing on critical pure modules; hypothesis invariants.
- Phase 4: dependency minors/patches by group (suite + `make llm-canary` + `make test-timeshift`).
- Phase 5: CI guardrails and the "useful test" definition in `docs/AGENTS.md`.

## Verification
Unit tests of the analysis (synthetic coverage JSON), a real `make test-audit` run whose numbers
match `coverage.xml`, `make lint && make type && make test`, ratchet.
