# Plan 163: Remove dead category helper and close the e2e engine

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7bf0c444..HEAD -- news_collector/editorial/categories.py news_collector/logic/workflows/pipeline_e2e.py`
> If either file changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (both items recorded by plan 140)
- **Category**: cleanup / test harness
- **Planned at**: commit `7bf0c444`, 2026-10-19

## Why this matters

Two small follow-ups recorded when plan 140 widened mutation coverage:

1. `news_collector/editorial/categories.py::is_generic_category` has **no
   caller and no test** (only stale copies under `build/lib/`, `temp/source/`
   and `mutants/`, which are artifacts). It survived as dead code because the
   mutation "no tests" mutants cannot be killed.
2. `news_collector/logic/workflows/pipeline_e2e.py` creates a
   `RefineryEngine` (line ~884) and never calls `close()`, leaking its audit
   worker thread in the E2E harness. The engine's own docstring
   (`refinery_engine.py:301-314`) says "every owner of an engine is expected to
   call this" and guarantees `close()` is idempotent. The harness already ends
   in a `finally:` that does nothing.

## Current state

- `news_collector/editorial/categories.py:133-134` —
  `def is_generic_category(value): return normalize_raw_category(value) in GENERIC_CATEGORIES`.
  `GENERIC_CATEGORIES` itself **is used** by
  `news_collector/editorial/category_resolver.py:8,82` — keep the set and
  `is_generic_source_category`.
- `news_collector/logic/workflows/pipeline_e2e.py:869` — `publication_db =
  DatabaseManager(...)` (unconditional); `:884-899` — `engine = RefineryEngine(...)`
  inside `if approved_article is not None:`; `:1023-1024` — the function's outer
  `finally: pass`.
- `news_collector/logic/workflows/refinery_engine.py:301` — `close()` calls
  `executor.shutdown(wait=False, cancel_futures=True)`; idempotent.
- `make test-e2e` runs the isolated pipeline E2E suite
  (`tests/e2e_pipeline/test_pipeline_e2e.py`), which exercises this harness.

## Commands you will need

| Purpose        | Command                                              | Provenance | Expected |
|----------------|------------------------------------------------------|------------|----------|
| Install        | `make bootstrap`                                     | declared   | exit 0   |
| Lint           | `make lint`                                          | declared   | exit 0   |
| Types          | `make type` (committed tree only)                    | declared   | exit 0   |
| Unit suite     | `make test`                                          | declared   | all pass |
| E2E harness    | `make test-e2e` (run it **twice**)                   | declared   | all pass |
| Ledger         | `make plans-ledger-check`                            | declared   | OK       |

Provenance: all `declared`.

## Scope

**In scope**: `news_collector/editorial/categories.py`,
`news_collector/logic/workflows/pipeline_e2e.py`.

**Out of scope**: `GENERIC_CATEGORIES`, `is_generic_source_category`,
`category_resolver.py`, any other workflow, the stale `build/`, `temp/`,
`mutants/` copies (do not edit artifacts).

## Steps

### Step 1: Delete the dead helper

1. Remove `is_generic_category` (and its blank lines) from
   `news_collector/editorial/categories.py`. Keep `GENERIC_CATEGORIES`.
2. Verify no references remain:
   `grep -rn "is_generic_category" --include="*.py" news_collector tests scripts` → 0.
3. `make lint && make test` (the module has tests; they must stay green).

**Verify**: grep 0; lint and unit suite green.

### Step 2: Close the e2e engine (and its DB)

4. Before the outer `try:` in `run_pipeline_e2e_scenario`, initialise
   `engine: RefineryEngine | None = None` and `publication_db: DatabaseManager | None = None`
   (so the `finally` is safe on every path).
5. Assign to those names where the objects are created (do not change the
   creation logic).
6. Replace the outer `finally: pass` with:
   ```python
   finally:
       if engine is not None:
           engine.close()
       if publication_db is not None:
           publication_db.close()
   ```
   Order matters: engine first (it may still reference the DB), then the DB.
7. `make test-e2e` **twice** (the harness is order/state sensitive; the second
   run proves no leaked thread or locked DB file), then `make test`.

**Verify**: both e2e runs green; unit suite green; no `ResourceWarning` /
"database is locked" in the output.

### Step 3: Gates

8. `make lint`, `make type` (**post-commit**), `make test`,
   `make test-boundaries`, `make plans-ledger-check`.

**Verify**: all exit 0.

## Done criteria

- [ ] `is_generic_category` has zero references; `GENERIC_CATEGORIES` untouched
- [ ] The harness closes the engine and the publication DB in `finally`
- [ ] `make test-e2e` passes twice
- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `git diff --name-only main...HEAD` lists exactly the two in-scope files
- [ ] Ledger row 163 updated by the reviewer

## STOP conditions

- `engine.close()` raises or the engine is used **after** the `finally` block's
  scope (report the call site).
- `publication_db` is closed elsewhere (double close) — report and drop only
  that part.
- The e2e suite fails on the unmodified checkout (broken baseline).
- Removing the helper reveals a hidden dynamic caller (e.g. `getattr` by name) —
  report.
