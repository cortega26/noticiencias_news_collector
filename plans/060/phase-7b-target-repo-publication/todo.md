# Plan 060 / Phase 7b todo — Target-repository publication workflow

Execution index for [`spec.md`](spec.md). The spec's scope boundaries, STOP
conditions, and done criteria are binding; do not implement from this checklist
alone.

## Step 0 — baseline + drift

- [x] Drift check clean at `28271c6`
- [x] Baseline: 273 passed on the touched suites command in spec.md

## Step 1 — workflow tests first

- [x] `tests/decompose_refinery/test_target_repo_publication.py` (13 tests)
  - [x] happy path + stage order
  - [x] missing output_filename
  - [x] writer ValueError
  - [x] fast frontmatter failure (+ taxonomy fallback)
  - [x] full validation failure
  - [x] no package.json → skipped
  - [x] PR None
  - [x] mark_article_publishing ordering/tolerance/None id
  - [x] deps read per call

## Step 2 — module

- [x] NEW `news_collector/logic/workflows/target_repo_publication.py`
      (`PublicationRequest`, `PublicationDeps`, `PublicationOutcome`,
      `TargetRepoPublicationWorkflow`)
- [x] `make lint` + new tests green
- [x] `lizard -C 8 -L 50 -a 8` clean (0 warnings)

## Step 3 — engine rewire

- [x] `self.publication_workflow = TargetRepoPublicationWorkflow()`
- [x] `_publish_to_target_repo` delegate; outcome mapped onto `PublicationRun`;
      audit + persist order unchanged
- [x] Eight helpers deleted; dead imports removed (`rg` → no matches)
- [x] `test_engine_regression.py` patch target updated to the new module
      (patch-target-only edit)
- [x] Targeted 286 passed; `make lint`

## Step 4 — gates + docs

- [x] `make lint && make test && make test-boundaries` exit 0
      (3229 passed, 3 passed)
- [x] `make type` → 3242 passed, `[coverage-ratchet] OK — total 92.28%,
      baseline 91.25%, changed files passed`
- [x] `make test-e2e` → 13 passed; `make quality-gate` → all snapshots valid
- [x] `docs/ARCHITECTURE.md` updated
- [x] `plans/060/todo.md` Phase 7 target-repo checkbox checked
- [x] `.venv/bin/python scripts/validate_plans_ledger.py` OK

## Independent review (fresh context, HEAD vs working tree)

No real behavior defects found. One low-severity divergence was found and
fixed: a falsy non-None `pr_result.pr_url` (`""` from GitHubPublisher when a
201/recovery response lacks `html_url`) was persisted as `null` instead of
`""`; the failure outcome now carries `pr_url` verbatim
(`test_falsy_pr_url_is_preserved_for_persistence`). Post-fix: 287 targeted +
3230 unit tests green.

## Behavior-preservation evidence

- Engine `record_stage` name multiset: HEAD 19 → engine 12 + workflow 7, with
  the removed names in the same relative order and the engine's remaining
  order unchanged (diff of `record_stage("…")` occurrences).
- Persisted attempt JSON pinned by the existing engine/decompose suites
  (success files, frontend failure classes) — 286 targeted tests green with no
  assertion changes.
- Collaborator seams (`engine.git`/`writer`/`pr_orchestrator` reassignment,
  `publication_attempts_dir` reassignment) pass unmodified via per-call
  `PublicationDeps`.
