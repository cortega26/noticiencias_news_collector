# Plan 060 / Phase 7b — Target-repository publication workflow

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> check off the Phase 7 target-repository item in `plans/060/todo.md`, update
> `docs/ARCHITECTURE.md` if it still names this seam as remaining, and validate
> the plans ledger. This is a phase folder under plan 060 — no new ledger row.
>
> **Drift check (run first)**:
> `git diff --stat 28271c6..HEAD -- news_collector/logic/workflows/refinery_engine.py tests/decompose_refinery/test_engine_regression.py`
> If either file changed since this spec was written, re-verify the "Current
> state" line references; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (behavior-preserving extraction on the publish path)
- **Depends on**: Phase 7a (landed, `28271c6`); Phase 3c attempt persistence
  (done). Phases 5/6 are not required for this slice.
- **Category**: tech-debt / architecture (LAW-B3, LAW-B9)
- **Planned at**: backend `28271c6`, 2026-09-25

## Why this phase exists

Plan 060 Phase 7 names one remaining Refinery seam:

> a target-repository publication workflow that composes the already
> extracted identity, writer, image, and PR collaborators.

Phase 7a extracted attempt recording + audit scheduling and split
`process_single_article` into stage methods. What remains in
`refinery_engine.py` is the publication tail — branch, write, frontend
validation, commit/push, PR — implemented as eight private methods on the
engine that reach into `self.writer` / `self.git` / `self.pr_orchestrator` /
`self.db`. This phase moves that tail into a focused, independently testable
module with a typed request/outcome, leaving the engine as the orchestrator
that owns identity, images, editing, policy gates, attempts and audit.

**Documented boundary deviation from the Phase 7 bullet:** identity and image
resolution remain upstream in the engine because the AI editor runs between
them and the target-repo stages (`identity → image → refine → slug → policy →
publish`). A collaborator cannot "compose" them behind the editor without
either taking an editor callback or covering the whole per-article flow; both
were rejected as larger, riskier rewrites than this phase's mandate. The
workflow composes the three genuine target-repo collaborators
(`TargetRepoWriter`, `GitHubPublisher`, `PROrchestrator`) plus the DB mark.

## Current state (verified at `28271c6`)

- `refinery_engine.py:756-786` `_publish_to_target_repo` — the sequence.
- Helpers to move: `_create_publication_branch:788-817`,
  `_write_post:819-841`, `_validate_post_frontend:843-860`,
  `_fast_frontmatter_guard:862-891`,
  `_run_full_frontend_validation:893-917`, `_commit_and_push:919-932`,
  `_create_pr_and_schedule_audit:934-967`.
- Stays in the engine: `_schedule_or_skip_audit:969-997` (audit seam),
  `_PublicationRun` attempt persistence, all earlier stages and gates.
- Dynamic test seams this extraction must preserve (collaborators are read per
  call, never captured at construction):
  - `engine.git = MagicMock()` post-construction —
    `tests/test_editorial_policy_enforcement.py:50`,
    `tests/test_refinery_contract_enforcement.py:80,111,170`,
    `tests/test_refinery_slug_security.py:50`.
  - `engine.writer.write_article = MagicMock(...)` in-place —
    `tests/unit/logic/workflows/test_refinery_engine.py:732,790,1102`,
    `tests/test_editorial_policy_enforcement.py:55`.
  - `engine.pr_orchestrator.create_pr = MagicMock(...)` in-place —
    `test_refinery_engine.py:1119`.
  - `engine.publication_attempts_dir = Path(tmpdir)` post-construction —
    `test_refinery_engine.py:152,198,246,331,365,392,429`.
- One test patches a module symbol that moves:
  `tests/decompose_refinery/test_engine_regression.py:199` patches
  `news_collector.logic.workflows.refinery_engine.run_frontend_publication_validation`.
  The patch target must become
  `news_collector.logic.workflows.target_repo_publication.run_frontend_publication_validation`
  (patch-target-only edit; no assertion changes).
- `TargetRepoWriter.write_article` (`target_repo_writer.py:51`),
  `PROrchestrator.create_pr` (`pr_orchestrator.py:53`),
  `run_frontend_publication_validation` (`frontend_publication_validation.py:401`),
  `validate_post_frontmatter_fast` (same file `:537`).

Baseline for the touched suites (verified, 2026-09-25, same command as 7a):

```bash
.venv/bin/pytest tests/decompose_refinery tests/unit/logic/workflows/test_refinery_engine.py \
  tests/test_editorial_policy_enforcement.py tests/test_policy_integrity.py \
  tests/integration/test_refinery_publish_hardening.py tests/integration/test_refinery_audit_staging.py \
  tests/integration/test_publishing_state_recovery.py tests/integration/test_refinery_canonical.py \
  tests/integration/test_refinery_image.py tests/test_refinery_contract_enforcement.py \
  tests/test_refinery_slug_security.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
# 273 passed
```

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/logic/workflows/target_repo_publication.py`
- `news_collector/logic/workflows/refinery_engine.py` — delete the moved
  helpers; `_publish_to_target_repo` becomes a thin delegate that maps the
  outcome onto `_PublicationRun`, then does audit + persist exactly as today.
- `tests/decompose_refinery/test_target_repo_publication.py` (new)
- `tests/decompose_refinery/test_engine_regression.py` — patch-target update
  only for the moved validation symbol.
- `docs/ARCHITECTURE.md` debt section; `plans/060/todo.md` Phase 7 checkboxes.

**Out of scope** (do NOT touch):

- Identity/image/refinement/gates stages, `_PublicationRun`, attempt
  persistence (`_persist_*`), audit scheduling (`_schedule_or_skip_audit`,
  `AuditScheduler`) — the workflow must NOT persist attempts or schedule
  audits; it returns an outcome and the engine keeps those side effects.
- `EditorAgent` typed stages and admin route split (Phase 7c/7d).
- `apps/refinery/**`, contracts, DB lifecycle tables.
- Any stage name, order, payload, log string, or error shape change.

## Design

### `target_repo_publication.py`

Stateless workflow + typed inputs/outputs; collaborators injected per call so
the engine's post-construction attribute reassignments keep working.

- `PublicationRequest` (frozen dataclass): `article`, `article_id`,
  `numeric_id`, `output_filename`, `refined_content`, `grounding_notes`,
  `target_repo_obj`, `target_dir`, `attempts_dir`.
- `PublicationDeps` (frozen dataclass): `writer`, `git`, `pr_orchestrator`,
  `db` — read from the engine at call time.
- `PublicationOutcome` (frozen dataclass): `success`, `branch_name`, `pr_url`,
  `validation_summary_path`, `failure_class`.
- `TargetRepoPublicationWorkflow.publish(request, deps, record_stage)` —
  verbatim move of the current sequence:
  1. missing `output_filename` → error log + `output_filename` stage, fail;
  2. `_create_publication_branch` (mark publishing via `deps.db` when
     `numeric_id` and `hasattr`; `git.create_branch`; `branch_created` stage);
  3. `_write_post` (`writer.write_article`; `file_written` stage; the
     `ValueError` path logs `S0 GUARD: {}` and records the failure);
  4. `_validate_post_frontend` (package.json absent → `skipped` stage; else
     compute `{artifact_name(article_id)}.frontend_validation.json` under
     `request.attempts_dir`, run the fast guard then the full validation,
     record `frontend_publication_validation`, carry `failure_class`);
  5. `_commit_and_push` (`commit_pushed` stage);
  6. `_create_pr` (`PROrchestrator.create_pr`); on `None` → error log +
     `pr_created` False; on success → info log + `pr_created` True.
  The method returns the typed outcome; it never writes attempt files and
  never calls audit methods.
- Internal helpers keep the fast/full validation split and stay under Codacy's
  limits (50 NLOC, CCN 8, 8 params).

### Engine wiring

- `__init__`: `self.publication_workflow = TargetRepoPublicationWorkflow()`.
- `_publish_to_target_repo`: build `PublicationRequest` from `run` +
  `self.publication_attempts_dir`; build `PublicationDeps` from
  `self.writer`/`self.git`/`self.pr_orchestrator`/`self.db`; call `publish`
  with `record_stage=run.record_stage`; map `branch_name`/`pr_url`/
  `validation_summary_path` onto `run`; on failure
  `run.persist_attempt(False, failure_class=outcome.failure_class)` and return
  False; on success keep the current order `_schedule_or_skip_audit(...)` then
  `run.persist_attempt(True)` then True.
- Delete the eight moved helpers and the now-unused
  `run_frontend_publication_validation` / `validate_post_frontmatter_fast`
  imports.

Because persistence now happens after the workflow returns, the persisted JSON
content must be byte-identical to today's for every outcome (same stages, same
field set at the same logical point). The new workflow unit tests pin the
stage order/payloads; the existing engine tests pin the file contents.

## Test plan

- New `tests/decompose_refinery/test_target_repo_publication.py` with mocked
  writer/git/PR/db:
  - happy path: branch → write → skipped/full validation → commit → PR;
    outcome fields set; stage order asserted via the recorder mock.
  - missing `output_filename` → fail, `output_filename` stage, no side effects.
  - writer `ValueError` → `file_written` False, no commit/PR.
  - fast frontmatter failure → failure_class fallback
    `taxonomy_contract_violation`, no full validation call.
  - full validation failure → `overall_failure_class` carried, no commit/PR.
  - no `package.json` → `skipped` stage + commit/PR proceed.
  - PR `None` → `pr_created` False, no crash.
  - `mark_article_publishing` called before `create_branch`; missing method
    tolerated; raising method logged and ignored.
  - collaborators read from `deps` (e.g. two different git mocks in one test
    file produce different branch names).
- Existing suites: 273 targeted tests stay green; the only existing-test edit
  is the patch-target update in `test_engine_regression.py`.

## Steps

### Step 0: Baseline + drift

Run the baseline command and the drift check. STOP on any non-green result or
in-scope drift.

### Step 1: Tests first

Write `test_target_repo_publication.py` against the module API (it fails until
Step 2). Keep it hermetic (`tmp_path` only, mock boundaries).

### Step 2: Implement the module

Verbatim move of the sequence per Design; no policy decisions, no new logging
content.

**Verify**: new tests pass; `make lint`.

### Step 3: Rewire the engine

Delegate `_publish_to_target_repo`, delete the moved helpers, wire
`publication_workflow`, drop dead imports; update the one patch target in
`test_engine_regression.py`.

**Verify**: targeted 273 + new tests green; `rg "run_frontend_publication_validation|validate_post_frontmatter_fast" news_collector/logic/workflows/refinery_engine.py` → no matches; `make lint`.

### Step 4: Full gates + docs

1. `make lint && make type && make test && make test-boundaries`
2. `make test-e2e` (publish path is exercised there) and `make quality-gate`.
3. `lizard -C 8 -L 50 -a 8` on the new module → no new-function warnings.
4. Update `docs/ARCHITECTURE.md` (drop the target-repo seam from remaining
   debt; name the new module) and `plans/060/todo.md` Phase 7 checkbox.
5. `scripts/validate_plans_ledger.py` → OK.

## Done criteria (machine-checkable)

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`,
      `make test-e2e`, `make quality-gate` all exit 0
- [ ] `target_repo_publication.py` exists; the engine contains none of the
      eight moved helper bodies (delegate only)
- [ ] No stage name/order/payload change: new workflow tests + existing 273
      engine tests green
- [ ] `git diff --name-only` lists only in-scope files (plus the allowed
      patch-target edit)
- [ ] Docs/plan checkboxes reconciled; ledger validator OK

## STOP conditions

Stop and report if:

- Drift check or baseline is not clean.
- Any stage name, order, payload, log string, or failure class would change.
- Collaborator reassignment seams (`engine.git` etc.) stop working, i.e. the
  workflow captures deps at construction instead of per call.
- Persisted attempt JSON differs from today's for any covered outcome.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch: `advisor/060-phase-7b-target-repo-publication`.
- Commit: `refactor(workflows): extract target-repo publication workflow`.
- Do NOT push or open a PR unless the operator instructed it.
