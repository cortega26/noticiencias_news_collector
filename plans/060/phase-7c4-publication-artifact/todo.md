# Plan 060 / Phase 7c-4 todo — Typed final publication artifact stage

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `e1daeaf`
- [x] Baseline editor suites green (434 passed, 1 skipped)

## Step 1 — tests first

- [x] `tests/unit/editorial/test_editorial_publication_artifact.py` (9 tests)
  - [x] happy path: frontmatter + envelope + hooks
  - [x] missing `override_date` → LAW-B5 `ValueError`
  - [x] V2 incomplete → `editorial_v2_incomplete`
  - [x] disputed fact-check → `editorial_fact_check_disputed`
  - [x] health-scope overclaim → `editorial_capability_overclaim`
  - [x] TL;DR Visual strip depends on `image_url`
  - [x] upstream `raw_text` enrichment overrides win
  - [x] `normalize_frontmatter` hook is applied

## Step 2 — module + rewire

- [x] NEW `news_collector/components/editorial/editorial_publication_artifact.py`
- [x] Moved definitions: `GeneratedArticleValidationError`,
      `_capability_overclaim_block`
- [x] `ai_editor.py` re-exports the moved symbols; removes the dead imports
      (`yaml`, `is_health_scope`, `resolve_hero_alt_text`, uncertainty helpers)
- [x] `process_article` ends with the single stage call (façade over the five
      typed stages)
- [x] `make lint` + editor suites green (456 passed, 1 skipped)

## Post-PR adjustment (Codacy)

- [x] Split `run_publication_artifact_stage` into pure module-level helpers
      (211 LOC / CCN 62 → under the Codacy limits) with the same statement
      order, dict insertion order and messages; artifact tests, guardrails and
      health-scope suites green (433 passed, 1 skipped)

## Independent review (fresh context, spec vs implementation)

- [x] Reviewer confirmed the verbatim move (strings/regexes/gates/order),
      re-exports (`is` identity), no cycle, no leftover imports
- [x] Findings applied: observability wording (loguru function/line follow the
      new frame), hook-application test, stronger happy-path assertions

## Step 3 — gates

- [x] `make lint` exit 0
- [x] `make type` exit 0 (3380 passed, 5 skipped; ratchet 92.62% vs 91.25%)
- [x] `make test` exit 0 (3367 passed, 5 skipped)
- [x] `make test-boundaries` exit 0 (3 passed)
- [x] `make quality-gate` snapshots valid
- [x] `plans/060/todo.md` annotated (7c-1..7c-4; provenance deferral rationale)
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK
