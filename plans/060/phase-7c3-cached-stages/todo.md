# Plan 060 / Phase 7c-3 todo — Typed cache-backed stages

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `a59ca1c`
- [x] Baseline editor suites green (429 passed, 1 skipped)

## Step 1 — tests first

- [x] `tests/unit/editorial/test_editorial_cached_stage.py` (5 tests)
  - [x] cache hit → value returned, `load_cached` once, no generate/persist
  - [x] unusable cache (`None`) → regenerate + persist
  - [x] cache absent → load never called, generate + persist
  - [x] generated value identity (dict payload)
  - [x] generate failure propagates without persist

## Step 2 — module + rewire

- [x] NEW `news_collector/components/editorial/editorial_cached_stage.py`
- [x] Stage 1 delegates with identical print + cache calls
- [x] Stage 6 delegates with identical parse/validate warnings and persist guard
- [x] Duplicated generate+persist body removed
- [x] `make lint` + editor suites green (439 passed, 1 skipped)

## Independent review (fresh context, spec vs implementation)

- [x] Reviewer confirmed no behavior drift, pure runner, no import cycle,
      no out-of-scope edits, monkeypatch contracts intact
- [x] Findings applied: hit test now pins a single `load_cached` call; phase
      checklist ticked with evidence

## Step 3 — gates

- [x] `make lint` exit 0
- [x] `make type` exit 0 (3372 passed, 5 skipped; ratchet 92.60% vs 91.25%)
- [x] `make test` exit 0 (3359 passed, 5 skipped)
- [x] `make test-boundaries` exit 0 (3 passed)
- [x] `make quality-gate` snapshots valid
- [x] `plans/060/todo.md` Phase 7 editor checkbox annotated (7c-1/7c-2/7c-3)
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK
