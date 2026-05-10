# Todo: Batch 4 — System Decomposition

Consult `spec.md` before every change. Run tests after every meaningful edit.

## Phase 0 — Setup and baseline

- [ ] Run `make test` to record pre-existing failure baseline
- [ ] Run `make test-boundaries` to record boundary baseline
- [ ] Read all four extraction targets end to end: `system/__init__.py:354-455`, `:457-578`, `:627-639`, `reporting.py:128-203`
- [ ] Confirm all three new test files are in place before starting extraction 1

## Phase 1 — ValidationCoordinator extraction

- [ ] Write `tests/unit/validation/test_validation_coordinator.py` with coverage for:
  - dry_run returns early with zeros
  - empty DB returns success with zeros
  - single batch of mixed valid/invalid articles
  - multiple batches aggregated correctly
  - MAX_BATCHES halt (infinite-loop guard)
- [ ] Create `news_collector/validation/coordinator.py` with `ValidationCoordinator` class
- [ ] Move `_execute_validation` body into `ValidationCoordinator.execute()`
- [ ] Wire delegation in `NewsCollectorSystem._execute_validation()`
- [ ] Run validation coordinator tests + `make test-boundaries` to confirm delegation works

## Phase 2 — ScoringCoordinator extraction

- [ ] Write `tests/unit/scoring/test_scoring_coordinator.py` with coverage for:
  - dry_run calls _simulate_scoring and returns
  - batch scoring path (async) with valid results
  - batch failure falls back to sequential scoring
  - sequential fallback raises when score_article_async is missing
  - empty payloads list (no articles to score)
  - all articles excluded (should_include=False)
  - DB bulk update called correctly
- [ ] Create `news_collector/scoring/coordinator.py` with `ScoringCoordinator` class
- [ ] Move `_execute_scoring` body into `ScoringCoordinator.execute()`
- [ ] Wire delegation in `NewsCollectorSystem._execute_scoring()`
- [ ] Run scoring coordinator tests + `make test-boundaries` to confirm delegation works

## Phase 3 — SessionReporter extraction

- [ ] Write `tests/unit/system/test_session_reporter.py` with coverage for:
  - full report generated with all sections
  - empty/no-data doesn't crash
  - health export succeeds
  - health export failure is non-fatal (logged, not raised)
- [ ] Create `news_collector/system/reporter.py` with `SessionReporter` class
- [ ] Move `generate_session_report` from reporting.py into `SessionReporter.generate_report()`
- [ ] Wire delegation in `NewsCollectorSystem._generate_session_report()`
- [ ] Run reporter tests + `make test-boundaries`

## Phase 4 — Final verification

- [ ] Run `make test` — all tests pass, zero regressions
- [ ] Run `make test-boundaries` — boundary tests pass
- [ ] Run `tests/unit/system/test_s1_refactor.py` — safety contracts hold
- [ ] `git diff` reviewed — only moved/redirected code, no new logic
- [ ] Remove `generate_session_report` from `reporting.py` exports (if re-exported)
- [x] Call fresh sub-agent: "review spec.md and the current implementation for gaps"
- [x] Fix Gap A: Remove dead `_simulate_scoring` from `system/__init__.py`
- [x] Fix Gap B: Remove dead `_simulate_collection` from `system/__init__.py`
- [x] Fix Gap C: Remove stale re-export imports from `system/__init__.py`
- [x] Fix Gap D: Remove stale `ContentValidator` import from `system/__init__.py`
