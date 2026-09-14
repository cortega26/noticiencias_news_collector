# Plan 080 — Phase 0 baseline

Recorded 2026-09-13, before any Phase 0/1 implementation edits.

## Repository state

- Backend repo: `noticiencias_news_collector`
  - HEAD: `32f7a94511e42006c63bee025f521f86d9de8711`
  - Branch: `main`
- Frontend repo: `noticiencias`
  - HEAD: `eb24b70497b1a11eafe1a54618dc0b3e8af70ec6`
  - Branch: `main`

### Dirty files at start (backend repo)

```
 M data/exports/latest_articles.json
 M news_collector/logic/workflows/pipeline_e2e.py
```

- `data/exports/latest_articles.json` — pre-existing uncommitted generated
  export snapshot, unrelated to this task. Left untouched, not committed, not
  inspected further.
- `news_collector/logic/workflows/pipeline_e2e.py` — concurrent unrelated WIP
  (a frontmatter-parsing fix owned by someone else, per task instructions).
  Not edited. Not read in detail. If any test run in this phase touches this
  file's behavior, that is noted as "concurrent unrelated WIP" rather than
  assumed away, reverted, or fixed here.

## Environment versions

- Python: `Python 3.13.12` (`.venv/bin/python --version`)
- Node: `v24.19.0` (`node --version`)

## Assigned scope

Plan 080, Phase 0 (this document) and Phase 1 (stateful workflow lifecycle
tests) only. Phase 2 (admin contracts) and Phase 3 (promptfoo editorial
replay) are explicitly out of scope for this session and were not started or
touched.

## Docs read before starting

- `AGENTS.md` (repo root)
- `docs/AGENTS.md` (full governance law, change matrix, §0.1 spec-driven
  workflow)
- `plans/080/spec.md`
- `plans/080/00-evidence.md`
- `plans/080/01-stateful-workflows.md`
- `plans/080/todo.md`
- `plans/archive/078-startup-less-lease-recovery/spec.md`
- `news_collector/logic/workflows/collection_run_workflow.py`
- `news_collector/logic/workflows/publication_run_workflow.py`
- `tests/unit/logic/workflows/test_collection_run_workflow.py`
- `tests/unit/logic/workflows/test_publication_run_workflow.py`
- `tests/conftest.py`
- `tests/property/test_normalization_properties.py` (existing Hypothesis
  usage pattern/convention in this repo's `tests/property/`)
- `news_collector/storage/database.py` (`DatabaseManager` — docstring/signature)
- `news_collector/storage/models.py` (`WorkflowRun` ORM model)

## Baseline command results (before any Phase 0/1 edits)

```
$ .venv/bin/python scripts/validate_plans_ledger.py
validate_plans_ledger: OK
EXIT: 0
```

```
$ .venv/bin/python -m pytest tests/unit/logic/workflows/test_collection_run_workflow.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
.............................................                            [100%]
45 passed in 13.81s
EXIT: 0
```

No pre-existing failures were found in either targeted baseline command. Both
are clean on the dirty checkout described above (the two uncommitted files
did not cause either command to fail or need special handling).

## Concurrent work check

`news_collector/logic/workflows/pipeline_e2e.py` is not read, imported, or
exercised by either baseline command above, nor by the new Phase 1 test file
(which targets only `collection_run_workflow.py` and
`publication_run_workflow.py`). No conflict with the concurrent frontmatter
fix is expected; none was observed.
