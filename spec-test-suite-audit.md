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

## Phase 3b-1 (done): kill mutation survivors in `failure_kinds` and `url_canonicalizer`
Files: `tests/unit/infrastructure/llm/test_failure_kinds_boundaries.py`,
`tests/unit/utils/test_url_canonicalizer_table.py`, `[tool.mutmut]` selection and `[tool.mutation.floors]`
in `pyproject.toml`. Design: read each surviving mutant (`mutmut show`), decide real gap vs equivalent/dead
code, and pin the behavior with a test (status-code edges, error message, `Retry-After`; a 59-row hand-reviewed
URL table also checked for idempotence, plus helper and LRU-cache tests). Production code is not touched.
Acceptance: `failure_kinds` 81 -> 91 %, `url_canonicalizer` 61 -> 85 % (same mutmut run conditions);
remaining survivors documented as equivalent/dead code; floors raised to 88 / 82. Verification: `make mutation`
score check, `make lint && make type && make test`.
## Phase 4a (done): remove unused dependencies (`nltk`, `textblob`)
`pip-audit` flagged `GHSA-8mgp-746c-j5xp` (nltk, no upstream fix) and its allowlist entry expired
2026-09-30. `git grep` shows neither package is imported anywhere in the repo, so both are removed from
`pyproject.toml`/`requirements.txt`; locks regenerated with `scripts/sync_lockfiles.py --install-pip-tools`
(only nltk, textblob, regex, tqdm, defusedxml left the locks); the allowlist entry, its test and `SECURITY.md`
are updated. Acceptance: suite passes in a venv built strictly from `requirements.lock`, `pip-audit` reports no
vulnerabilities, `sync_lockfiles.py --check` clean after commit. Phase 4b (minor/patch upgrades by group) follows.
