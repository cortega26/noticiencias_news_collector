# Plan 060 / Phase 7a todo — Refinery recording + audit seams

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `a9a75be` (no in-scope changes)
- [x] Baseline: 250 passed on the touched suites command in spec.md

## Step 1 — publication-attempt recording extraction

- [x] Wrote `tests/decompose_refinery/test_publication_attempts.py` (11 tests)
- [x] NEW `news_collector/logic/workflows/publication_attempts.py`
      (`artifact_name`, `persist_publication_attempt`,
      `persist_interrupted_attempt`, `read_publication_attempt`)
- [x] Engine: delegates only; `publication_attempts_dir` still read at call time
- [x] `publication_run_workflow._read_attempt_for_id` → new module; dropped
      `RefineryEngine` import (two docstring mentions kept as architecture
      context — no dependency; the spec's "no matches" verify was met as
      "no import", confirmed by `grep "^from.*RefineryEngine\|^import.*RefineryEngine"`)
- [x] `pipeline_e2e.py` name call → `artifact_name`
- [x] `make lint` + targeted suites green (261 passed after Step 1)

## Step 2 — audit scheduler extraction

- [x] Wrote `tests/decompose_refinery/test_audit_scheduler.py` (12 tests)
- [x] NEW `news_collector/logic/workflows/audit_scheduler.py` (`AuditScheduler`)
- [x] Engine: `audit_scheduler` wired; `_last_audit_future` is a property over
      `audit_scheduler.last_future` (spec amended: the test at
      `test_refinery_engine.py:1262` assigns it directly); delegates inject
      `auditor`, `executor` and a late-bound `status_recorder` at call time
      (spec amended: `:1307` patches `_record_audit_status` *after* scheduling,
      so the callback must resolve it per invocation)
- [x] Audit tests green (`test_refinery_audit_staging`, engine audit unit tests)
- [x] `make lint` + targeted suites green (273 passed after Step 2)

## Step 3 — stage split (mechanical only)

- [x] `_apply_contract_guard` extracted (sentinel keeps the
      validator-returns-None behavior identical)
- [x] `_attempt_publishing_recovery` extracted (stores `run.numeric_id`)
- [x] `_resolve_identity` extracted
- [x] `_resolve_article_image` extracted
- [x] `_refine_article` extracted (returns `(refined, grounding_notes) | None`)
- [x] `_enforce_publication_gates` extracted
- [x] `_publish_to_target_repo` extracted (7 keyword params; within the spec's
      ~8 limit — the target-repo *collaborator* extraction stays deferred to
      7b)
- [x] `_PublicationRun` state holder replaces the closures; every
      `record_stage`/`persist_attempt` call kept in the same order
- [x] `# noqa: C901` removed (complexity now under the configured max 10)
- [x] Deferred-to-7b note: target-repository publication workflow collaborator
      + `EditorAgent` stages + admin route split (plan 060 todo Phase 7)

## Step 4 — gates + docs

- [x] `make lint` green; `make test` 3216 passed, 5 skipped; `make type`
      3229 passed + `[coverage-ratchet] OK — total 92.38%, baseline 91.25%`;
      `make test-boundaries` 3 passed
- [x] `docs/ARCHITECTURE.md` debt section updated
- [x] `docs/dev/source-of-truth-backlog.md` entry reconciled (CLOSED, residual
      tracked)
- [x] `plans/060/todo.md` Phase 7 first two boxes annotated
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK

## Deviations from spec (recorded)

1. The spec's Step 1 verify asked for zero `RefineryEngine` string matches in
   `publication_run_workflow.py`; two module-docstring mentions remain as
   architecture context. The done criterion that matters — no import — holds.
2. The spec initially claimed nothing outside the engine references
   `engine._last_audit_future`; `test_refinery_engine.py:1262` does. Spec
   amended to keep a property shim instead of deleting the attribute.
3. Accepted difference: `AuditScheduler` holds the db manager passed at
   construction, while the original `_record_audit_status` read `self.db` per
   call. No caller reassigns `RefineryEngine.db` after construction (verified
   by grep); recorded in the spec's Design §3.
4. `_persist_interrupted_attempt` delegates straight to
   `publication_attempts.persist_interrupted_attempt` instead of round-tripping
   through the engine's `_persist_publication_attempt_summary`; payload is
   identical (`target_repo` was already `None` on that path). A hypothetical
   subclass patch of the summary method would no longer intercept interrupted
   writes; no subclass exists.

## Follow-up: Codacy gate compliance (same PR)

The first push produced 9 new Codacy complexity issues (limits: 50 NLOC,
CCN 8, 8 parameters). Fixed in the same PR without behavior change:

- `AuditScheduler.schedule` now takes one `AuditRequest` instead of five loose
  fields; `_on_done` delegates coercion to `_coerce_audit_result`.
- `persist_publication_attempt` takes one `PublicationAttempt` record;
  `persist_interrupted_attempt` uses `_has_successful_attempt`.
- `process_single_article`, `_refine_article` and `_publish_to_target_repo`
  split further: `_audit_should_run`, `_record_advisory_stages`,
  `_create_publication_branch`, `_write_post`, `_validate_post_frontend`,
  `_fast_frontmatter_guard`, `_run_full_frontend_validation`,
  `_commit_and_push`, `_create_pr_and_schedule_audit`,
  `_schedule_or_skip_audit`.
- Type narrowing restored with `cast` for the values
  `_create_publication_branch` guarantees (`mypy` clean; 7 errors fixed).

Re-verified: targeted 273 tests green; `make lint`; `make type` (3229 passed,
ratchet 92.25% vs 91.25%); `make test-boundaries`; `make quality-gate`;
`lizard -C 8 -L 50 -a 8` clean for every changed function.

## Independent review

Fresh-context review (plan 060 §0.1(d)) compared HEAD vs working tree by
normalized method bodies: no real behavior defects found; stage/persist order
and payloads identical (39 calls each side), all test seams preserved.
