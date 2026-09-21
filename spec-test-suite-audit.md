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

## Phase 1a (done): obsolete tests
Removed `tests/spikes/` (32 tests of self-contained prototypes), `tests/legacy/` (a print-only script and a
self-testing helper) and the uncollected `verify_*`/`debug_*` scripts (one imported a non-existent module).
Acceptance: suite 2909 -> 2876 (-33), covered lines of real code unchanged (17 190), ratchet OK, the two spike
documents note where the prototypes can be recovered from git.

## Phase 1b (done): orphan scripts
26 one-off scripts removed. Criteria (all required): zero references outside archived plans and the generated
inventory (checked with `git grep` for `scripts/x`, `scripts.x`, `x.py` and imports), last change Feb-Jun 2026,
0 % coverage, name/content of a diagnostic, demo, benchmark, one-time patch or duplicate check. Kept for the
owner to decide: `audit_pipeline.py` (unified source-audit entry point that composes still-live pieces; restored after review), recently modified tools, `migrate_metrics_db.py` (a migration), and the two report generators.
Acceptance: suite unchanged (2882 passed), ratchet OK, lint clean.

## Phase 3a (done): mutation testing
`[tool.mutmut]` (mutmut 3) over five pure critical modules with a curated test selection; `make mutation`
installs mutmut in `.mutlib` (never in the venv) and runs `scripts/mutation_score.py --check`, which reads
`mutants/**/*.meta`, prints a per-module score (detected / judged) and fails below `[tool.mutation.floors]`.
`.github/workflows/mutation.yml` runs it weekly and writes the table to the step summary. Acceptance: score
script unit-tested with synthetic meta files; admission survivors killed (102/102); baseline documented.
