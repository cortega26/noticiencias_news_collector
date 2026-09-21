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

## Phase 4b-1 (done): dependency group "web/http/validation"
`scripts/sync_lockfiles.py` gains `--upgrade-package NAME[==VER]` (repeatable; `build_compile_args` puts one
`--upgrade-package` per name before the input file; everything else keeps its pin), unit-tested. Used to bump
starlette, pydantic(+core), anyio, urllib3, certifi, idna, charset-normalizer, typing-extensions,
annotated-types and click in all three locks (nothing else moved). Acceptance, in a venv built strictly
from the new lock: full suite 3078 passed; `make llm-canary --require-keys` 20/20; time-shifted suite only
fails the two expiring pip-audit tests by design; `sync_lockfiles.py --check` clean. New third-party
deprecation (starlette TestClient x anyio 4.15) filtered in `pyproject.toml`.

## Phase 4b-2 (done): dependency group "data/ML"
Same procedure as 4b-1 (`sync_lockfiles.py --upgrade-package`): alembic 1.20.0, sqlalchemy 2.0.54, numpy 2.5.3,
scikit-learn 1.9.1, scipy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, greenlet 3.5.6, mako 1.4.1, orjson 3.12.0
(scikit-learn/scipy add `cloudpickle` and `narwhals` as transitive deps). Acceptance in a venv built strictly
from the lock: full suite 3097 passed (incl. Alembic migration tests), `make llm-canary --require-keys` 20/20,
time-shifted suite only fails the expiring pip-audit tests by design, `sync_lockfiles.py --check` clean.

## Phase 4b-3 (done): dependency group "scraping"
playwright/patchright 1.63.0, curl-cffi 0.16.3, beautifulsoup4 4.15.0, lxml 6.1.3, feedparser 6.0.14,
cssselect 1.5.0, cffi 2.1.1, apify-fingerprint-datapoints 0.15.0. `curl-cffi` 0.16 no longer requires `rich`
(so `rich`, `pygments`, `markdown-it-py`, `mdurl` leave the runtime lock; the repo imports none of them);
feedparser swaps `sgmllib3k` for `feedparser-sgmllib`. Acceptance: suite 3097 passed and canary 20/20 in a
venv built strictly from the lock; imports of playwright/scrapling/feedparser/bs4/lxml OK; **live parse of 8
configured feeds is byte-for-byte equivalent between feedparser 6.0.12 and 6.0.14** (entry count + content
hash); `sync_lockfiles.py --check` clean.

## Phase 4b-4 (done): tooling group + fix of `--upgrade-package`
Bug found while upgrading: `pip-compile --upgrade-package X` **adds** X when a lock does not contain it, so passing
`semgrep` pulled the whole security toolchain (and a protobuf downgrade) into the runtime lock. `sync_lockfiles.py`
now applies each requested package only to the locks that already pin it (`pinned_names`, `upgrades_for_lock`,
unit-tested). Result: only `bandit` 1.9.3->1.9.4 and `hypothesis` 6.165.5->6.168.0 move (security lock).
Acceptance: venv built strictly from `requirements-security.lock`: suite 3099 passed, bandit findings identical
(same counts as 1.9.3), `sync_lockfiles.py --check` clean. `semgrep` cannot move (its rich/protobuf pins);
ruff/mypy/coverage/black/isort/pytest-randomly are not in any lock (installed by bootstrap) - left to the owner.
## Phase 2b (done): measure `noticiencias` and raise the ratchet floor
`--cov`/`[tool.coverage.run] source` now include `noticiencias` (config schema/manager = the sealed
cross-repo contract); `noticiencias/gui_config.py` (legacy Streamlit GUI, needs Streamlit) is omitted like
`apps/refinery/admin_panel.py`. `.coverage-baseline` re-recorded with `coverage_ratcheter.sh record` and a
noise margin (line 91.25 / branch 80.92; measured 91.75 / 81.92). The script's hard-coded minimums stay
(their tests use synthetic totals); the baseline is the effective floor. Acceptance: full suite 3097 passed,
`coverage_ratcheter.sh check` OK against the new baseline, ratchet unit tests unchanged.

## Phase 5 (done): permanent guardrails

`.github/workflows/test-health-weekly.yml` runs the suite weekly with the clock moved +14 days
(`TIME_SHIFT_DAYS`, `time_shift_plugin`): it fails first on time-dependent tests and on accepted-risk
exceptions expiring within two weeks (pip-audit allowlist). `docs/AGENTS.md` §4.1 states the review criteria for
useful tests (real code, real assertions, mocks only at boundaries, no implementation pinning, no "today"),
points to mutation testing as the regression-detection measure and requires a regression test per bug fix.
Together with the ratchet baseline (2b) and mutation floors (3a) these are the standing guardrails.

## Phase 3b-2 (done): survivors in `grounding` and `llm_run_report`
Same method as 3b-1 (`mutmut show` -> real gap vs equivalent). Files: `tests/unit/editorial/test_grounding_shapes.py`,
`tests/unit/observability/test_llm_run_report_shapes.py`, a rewritten emit test, `[tool.mutmut]` selection and floors
(grounding 85, llm_run_report 85). Production code untouched. Acceptance: grounding 79 -> 89 %, llm_run_report
67 -> 88 %, `make mutation` check passes with the new floors, `make lint && make type && make test`.
