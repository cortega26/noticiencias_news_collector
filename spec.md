# Spec: Architectural Modernization — CI, Dead Code, Documentation

## Goals

Deliver high-ROI, low-risk improvements to the repository's CI infrastructure, dead-code
surface, and documentation alignment. No production Python code is modified.

## Completed

| Item | Status | Verification |
|---|---|---|
| Composite action `.github/actions/setup-python-env/` | DONE | Exists |
| `ci.yml` — 12 jobs use composite action | DONE | 12 occurrences |
| `e2e.yml`, `daily_collector.yml`, `source_reliability.yml` — simplified | DONE | No old pattern |
| `live-source-drift.yml`, `publication-smoke.yml` — simplified | DONE | No old pattern |
| `main.py` removed | DONE | File deleted |
| `tests/test_error_handling.py` removed | DONE | File deleted |
| README, AGENTS.md, INDEX.md, docs aligned | DONE | 7 files updated |
| source-of-truth-backlog.md entry closed | DONE | Marked CLOSED |
| `make lint` | PASS | Clean |
| `make type` | PASS | Mypy + coverage 87.81% |
| `make test` | PASS | 961 passed, 2 skipped |

## Remaining

| # | Item | Verification |
|---|---|---|
| R1 | Update `docs/CHANGELOG.md` with this session's changes | grep for session description |
| R2 | Run `make test-contracts` for contract boundary safety | `echo $?` = 0 |
| R3 | Run `make test-boundaries` for boundary safety | `echo $?` = 0 |
| R4 | Check `context/modules/` for stale paths vs current code | ls + grep |
| R5 | Git diff final review | No Python production code changed |

## Non-Goals

- Modifying production Python code
- Refactoring RefineryEngine (in-flight work, AGENTS.md §9)
- Changing contracts or adapters
- Modifying audit docs (non-authoritative per SOURCE_OF_TRUTH.md)
