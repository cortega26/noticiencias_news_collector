# Plan 060 / Phase 7c-2 todo — Typed critic gate for the EditorAgent repair loops

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `48589d8`
- [x] Baseline editor suites green (420 passed, 1 skipped)

## Step 1 — tests first

- [x] `tests/unit/editorial/test_editorial_critic_gate.py` (9 tests)
  - [x] pass on first verdict
  - [x] recoverable rejection → repair (fallback vs repairable base) → pass
  - [x] rejection → repair → cache-write ordering pinned with a shared log
  - [x] `None` verdict reason passed through to `repair` unchanged
  - [x] irrecoverable verdict: no repair, failure code preserved
  - [x] exhausted retries: last repaired content + failure code, no pass
  - [x] `max_retries=0`: single-verdict path, no pass/rejection/repair
  - [x] negative retry budget rejected before any evaluation
  - [x] policy constants match historical retry budgets/stage identities

## Step 2 — module + rewire

- [x] NEW `news_collector/components/editorial/editorial_critic_gate.py`
- [x] `ai_editor.py` Stage 3 uses `TECHNICAL_CRITIC_GATE` + `run_critic_gate`
- [x] `ai_editor.py` Stage 4 uses `EDITORIAL_CRITIC_GATE` + `run_critic_gate`
- [x] All prints, warnings, raises and cache/checkpoint writes byte-identical
- [x] `make lint` + editor suites green (432 passed, 1 skipped: 420 baseline
      + 7 gate tests + 5 e2e guardrail tests)

## Independent review (fresh context, spec vs implementation)

- [x] Reviewer confirmed no behavior drift, no out-of-scope edits, 2-tuple and
      3-tuple `_critic_pass` paths preserved, no import cycle
- [x] Findings applied: spec wording on the negative-budget `ValueError` and
      the `repair` signature (`str | None`); test gaps closed (ordering,
      `None` reason, negative budget, missing no-pass/rejection assertions)

## Step 3 — gates

- [x] `make lint` exit 0
- [x] `make type` exit 0 (3365 passed, 5 skipped; ratchet 92.43% vs 91.25%)
- [x] `make test` exit 0 (3352 passed, 5 skipped)
- [x] `make test-boundaries` exit 0 (3 passed)
- [x] `make quality-gate` snapshots valid
- [x] `plans/060/todo.md` Phase 7 editor checkbox annotated (7c-1 + 7c-2)
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK
