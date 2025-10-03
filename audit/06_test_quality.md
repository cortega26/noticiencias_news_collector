# Phase 6 — Test Quality & Mutation Planning

## Summary
- Ran `pytest --cov=src --cov-report=term-missing` to capture current coverage for core packages.
- Added Hypothesis-based property suites for reranker and text normalizer utilities to raise confidence in deterministic behavior.
- Provisioned MutMut configuration, CI workflow, and a targeted smoke harness so future mutation runs are turnkey.

## Coverage Snapshot
| Module | Coverage | Uncovered lines |
| --- | --- | --- |
| `src/reranker/reranker.py` | 97% | 51 |
| `src/utils/text_cleaner.py` | 89% | 32, 42-43, 51, 91 |
| `src/utils/dedupe.py` | 95% | 30, 33 |
| Repository total | 69% | See pytest report for full listing |

## Observed Gaps
- `src/scoring/basic_scorer.py` remains at 11% coverage with large swaths of logic (54-898) untested; prioritise regression suite covering scoring feature toggles.
- `src/utils/logger.py` has 41% coverage; instrumentation pathways and exception handling branches need fixtures.
- Storage layer (`src/storage/database.py`) sits at 76% with many branches omitted; integration stubs or mocking around database adapters could close gaps.

## Mutation Testing Plan
- Environment constraint: MutMut installation kept below the requested 5-minute window, but a full mutation run is deferred to CI/local due to expected runtime.
- Local workflow:
  1. `pip install -r requirements.txt mutmut`
  2. `python -m pytest tests/mutation_smoke` (fast guard against regressions)
  3. `mutmut run && mutmut results`
- CI workflow (`.github/workflows/mutation.yml`) schedules weekly Monday runs at 06:00 UTC and allows manual dispatch.
- Smoke harness (`tests/mutation_smoke/`) keeps mutants focused on reranking and normalization hotspots to surface regressions quickly.

## Next Steps
- Create focused tests for scoring pipelines to lift coverage above the 80% project target.
- Expand Hypothesis strategies to cover URL canonicalization and datetime normalization edge cases.
- Evaluate incremental mutation thresholds (e.g., failing PRs when surviving mutants touch changed files) once baseline run stabilises.
