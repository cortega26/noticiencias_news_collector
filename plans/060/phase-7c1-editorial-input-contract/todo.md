# Plan 060 / Phase 7c-1 todo — Typed editorial input + stage cache identity

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `f354044`
- [x] Baseline: 404 passed, 1 skipped (editor suites command in spec.md)

## Step 1 — tests first

- [x] `tests/unit/editorial/test_editorial_input.py` (16 tests)
  - [x] dict extraction fidelity (fields, fallbacks, categories)
  - [x] article_id derivation matrix (dict/str/explicit/unknown/hash)
  - [x] EditorialStage values + cache filename formatting

## Step 2 — modules + rewire

- [x] NEW `news_collector/components/editorial/editorial_stages.py`
- [x] NEW `news_collector/components/editorial/editorial_input.py`
- [x] `ai_editor.py`: input block uses `EditorialInput.from_raw`; five cache
      literals replaced by `EditorialStage`; nothing else touched
- [x] `make lint` + editor suites green (420 passed, 1 skipped)

## Independent review (fresh context, HEAD vs working tree)

No real defects; 33-case differential replay of the HEAD extraction against
`EditorialInput.from_raw` found 0 mismatches (values and runtime types),
cache filenames identical, diff limited to the 8 expected hunks. One accepted
difference: HEAD re-read `raw_text.get("metadata")` up to three times, the
dataclass reads it once before deriving `source_url`/`metadata_category` —
identical for every real payload type (dict/JSON/Pydantic dump); only a
non-deterministic dict subclass could observe it.

## Step 3 — gates

- [x] `make lint && make type && make test && make test-boundaries` exit 0
      (test 3246 passed; type 3259 passed, ratchet 92.31% vs 91.25%)
- [x] `make quality-gate` snapshots valid
- [x] `plans/060/todo.md` Phase 7 editor checkbox annotated (7c-1 partial)
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK
