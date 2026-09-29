# Plan 060 / Phase 7a — Refinery publication-attempt recording + audit seams

> **Executor instructions**: Follow this spec step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition triggers, stop and report — do not improvise. When done,
> check off `plans/060/todo.md` Phase 7's first two boxes (or annotate them),
> update `docs/ARCHITECTURE.md` §"RefineryEngine is still too broad", and
> reconcile `docs/dev/source-of-truth-backlog.md`'s `Decompose RefineryEngine`
> entry. Do not edit `plans/README.md` (this is a phase folder under plan 060,
> not a new ledger row).
>
> **Drift check (run first)**:
> `git diff --stat a9a75be..HEAD -- news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/publication_run_workflow.py news_collector/logic/workflows/pipeline_e2e.py tests/decompose_refinery/ tests/unit/logic/workflows/test_refinery_engine.py`
> If any in-scope file changed since this spec was written, re-verify the
> "Current state" line references before proceeding; on a mismatch, treat it
> as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: Plan 060 Phases 0-4c (done: Phases 3a/3b/3c durable lifecycle
  schema + dual-write are the backing store for the recorder). Phase 5/6 are
  **not** required for this slice, unlike the editor/admin-route slices.
- **Category**: tech-debt / architecture (LAW-B3, LAW-B4, LAW-B9)
- **Planned at**: backend `a9a75be`, 2026-09-24

## Why this phase exists

The source-of-truth backlog item `Decompose RefineryEngine` (high) named four
collaborators — publication identity, target-repo writes, image briefs, PR
orchestration — and all four already exist (`PublicationIdentityResolver`,
`TargetRepoWriter`, `ImageBriefStore`/`ArticleImageHandler`, `PROrchestrator`,
plans 057/093/094). The item is stale as written; the remaining concentration is
scoped by plan 060 Phase 7:

> retain `RefineryEngine.process_articles(...)`/`process_single_article(...)`;
> extract only remaining seams: a typed publication-attempt recorder backed by
> phase 3; a target-repository publication workflow; audit scheduling/recording
> where independently testable.

This phase executes the **recording + audit** seams (7a). The larger
target-repository publication workflow extraction, the `EditorAgent` stages and
the admin-route split remain Phase 7b/7c (see "Out of scope").

`refinery_engine.py` is 1,136 lines. `process_single_article` alone is ~440
lines behind a `# noqa: C901`, and `__init__` mixes policy bootstrap, runtime
dirs, attempt persistence, a background audit thread and collaborator wiring.
This phase moves the two self-contained I/O/state-machine concerns out of the
engine without changing any stage, order, or payload:

1. Every publication-attempt artifact read/write lives in one module next to
   its schema (`PublicationAttemptSummary`), so the writer (engine) and the
   readers (`publication_run_workflow`, `pipeline_e2e`, ops scripts) cannot
   drift on naming or format.
2. The optional-auditor lifecycle (threadpool, backpressure, callback result
   parsing, status persistence) lives in one independently testable unit.

## Current state (verified at `a9a75be`)

- `news_collector/logic/workflows/refinery_engine.py`
  - `__init__` builds attempts dir at `:191-192`; auditor + threadpool at
    `:199-207` (`self.executor`, `self._last_audit_future`).
  - Attempt persistence: `_persist_publication_attempt_summary` `:775-809`,
    `_safe_publication_artifact_name` `:811-814` (static),
    `_persist_interrupted_attempt` `:816-856`.
  - Audit lifecycle: `_record_audit_status` `:858-886`,
    `_schedule_optional_audit` `:888-988`.
- Consumers of the artifact-name static:
  - `publication_run_workflow.py:487-501` `_read_attempt_for_id` imports
    `RefineryEngine` **only** for `_safe_publication_artifact_name`.
  - `pipeline_e2e.py:914` via the engine instance.
  - `tests/unit/logic/workflows/test_publication_run_workflow.py:250-256`.
- Injection seams the tests already rely on (must keep working):
  - `tests/integration/test_refinery_audit_staging.py:47` —
    `engine.executor = _ImmediateExecutor()`.
  - `tests/unit/logic/workflows/test_refinery_engine.py:1259-1345` — patches
    `engine._record_audit_status` and replaces `engine.executor` to drive the
    backpressure / submission-failure / callback-crash paths.
  - `tests/unit/logic/workflows/test_refinery_engine.py:152,198,…` — reassigns
    `engine.publication_attempts_dir = Path(tmpdir)` **after construction** to
    redirect writes; the attempts dir must therefore be read dynamically at
    call time, never captured at construction.
- Existing collaborator style to match: `image_handler.py`, `pr_orchestrator.py`,
  `publication_identity.py`, `target_repo_writer.py` (focused classes/functions,
  module docstring stating role, `NewsCollectorLogger` module logger).
- `db.lifecycle` (`LifecycleRepository`) already receives the durable
  `publication_attempts` rows through the Phase 3c dual-write facade
  (`database.py`), so this phase does not add DB writes — it extracts the
  **JSON artifact** recording that the workflow/admin UI reads.

Baseline for the touched suites (verified, 2026-09-24):

```bash
.venv/bin/pytest tests/decompose_refinery tests/unit/logic/workflows/test_refinery_engine.py \
  tests/test_editorial_policy_enforcement.py tests/test_policy_integrity.py \
  tests/integration/test_refinery_publish_hardening.py tests/integration/test_refinery_audit_staging.py \
  tests/integration/test_publishing_state_recovery.py tests/integration/test_refinery_canonical.py \
  tests/integration/test_refinery_image.py tests/test_refinery_contract_enforcement.py \
  tests/test_refinery_slug_security.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
# 250 passed
```

## Scope

**In scope** (the only files to modify):

- NEW `news_collector/logic/workflows/publication_attempts.py` — artifact-level
  API for publication attempts: `artifact_name`, `persist_publication_attempt`,
  `persist_interrupted_attempt`, `read_publication_attempt`.
- NEW `news_collector/logic/workflows/audit_scheduler.py` — `AuditScheduler`.
- `news_collector/logic/workflows/refinery_engine.py` — delete the moved code,
  keep thin delegates + attribute compatibility.
- `news_collector/logic/workflows/publication_run_workflow.py` — read via the
  new module; drop the `RefineryEngine` import.
- `news_collector/logic/workflows/pipeline_e2e.py` — name via the new module.
- `tests/decompose_refinery/test_publication_attempts.py` (new),
  `tests/decompose_refinery/test_audit_scheduler.py` (new).
- `docs/ARCHITECTURE.md` debt section; `docs/dev/source-of-truth-backlog.md`
  entry; `plans/060/todo.md` Phase 7 annotations.
- `process_single_article` **only if** Step 3 is achievable as a mechanical
  method split (see Step 3); otherwise it is explicitly deferred to 7b.

**Out of scope** (do NOT touch):

- `_enforce_editorial_policy` / `_log_enforcement_decision` and the policy
  integrity check in `__init__` — heavy direct-test coupling; the policy gate
  is a later Phase 7 seam.
- `TargetRepoPublicationWorkflow` (the branch→write→validate→commit→PR
  collaborator), `EditorAgent` stages, admin route split — Phase 7b/7c.
- `db.lifecycle` / durable-table writes — Phase 3c already owns them.
- Changing any JSON shape, stage name/order, error text, or PR behavior.
- `apps/refinery/**` — legacy panel keeps working through the engine façade.

## Design

### 1. `publication_attempts.py`

Module-level functions (the callers own the attempts dir; format + naming are
single-sourced here):

- `artifact_name(article_id: str) -> str` — verbatim regex move from the engine
  static.
- `persist_publication_attempt(attempts_dir: Path, *, article_id, success,
  stages, target_repo=None, output_filename=None, final_slug=None,
  branch_name=None, pr_url=None, validation_summary_path=None,
  failure_class=None) -> Path` — verbatim move of
  `_persist_publication_attempt_summary` (same `PublicationAttemptSummary`,
  same `datetime.now(timezone.utc)` `generated_at`, same exact-key passthrough —
  do NOT add `model_dump(exclude_none=True)` or any field filtering).
- `persist_interrupted_attempt(attempts_dir: Path, article_id: str, stages) -> None`
  — verbatim move of `_persist_interrupted_attempt` (never overwrite an
  existing `success: true` file, never raise, no `failure_class`).
- `read_publication_attempt(attempts_dir: Path, article_id: str) -> dict | None`
  — verbatim move of `publication_run_workflow._read_attempt_for_id`'s file
  logic (exact match only, `None` on missing/corrupt).

Why functions, not a class: the dir is caller-owned (tests reassign
`engine.publication_attempts_dir` post-construction), so a stateful store would
fight the existing seam; this matches the `_run_metadata.py` / module-function
precedent. LAW-B9 proof: one artifact format, four call sites (engine writer ×2,
workflow reader, e2e harness).

### 2. `audit_scheduler.py`

`AuditScheduler` owns the optional post-PR auditor lifecycle as a state machine:

- `__init__(self, db)` — no I/O, no threadpool creation.
- `record_status(article_numeric_id, status, reason, attempts,
  timeout_seconds=None, model=None, endpoint=None)` — verbatim move of
  `_record_audit_status` (no-op on `None` id or non-callable db method; swallow
  and log db errors).
- `schedule(*, auditor, executor, status_recorder, article_id,
  article_numeric_id, content, source_url, article_data) -> None` — verbatim
  move of `_schedule_optional_audit`, with three injections replacing engine
  attributes: `auditor`, `executor` and `status_recorder`. Owns
  `self.last_future` (the backpressure flag, previously
  `engine._last_audit_future`). All status writes inside — including the
  backpressure skip, submission failure, callback crash, invalid result
  type, and parsed result — go through `status_recorder`.
  - `tests/unit/logic/workflows/test_refinery_engine.py:1262` assigns
    `engine._last_audit_future = pending` and `:1307` patches
    `engine._record_audit_status` *after* scheduling but *before* invoking the
    captured callback. Both seams must keep working:
    - the engine keeps a `_last_audit_future` **property** that reads/writes
      `audit_scheduler.last_future` (compatibility shim, same convention as
      the `_extract_slug`/`_download_image` delegates);
    - the engine passes `status_recorder` as a late-bound lambda
      (`lambda *a, **kw: self._record_audit_status(*a, **kw)`) so
      `patch.object(engine, "_record_audit_status")` still intercepts
      callback-time writes — passing the bound method directly would capture
      the unpatched method and break `:1307`.

Engine wiring (behavior-identical):

- `self.executor = ThreadPoolExecutor(max_workers=1)` stays in `__init__`
  (test injection point).
- `self.audit_scheduler = AuditScheduler(self.db)`.
- `_record_audit_status(...)` → delegate to `audit_scheduler.record_status`.
- `_schedule_optional_audit(...)` → delegate with
  `auditor=self.auditor, executor=self.executor,
  status_recorder=self._record_audit_status` resolved at call time.
- `_last_audit_future` becomes a property forwarding to
  `audit_scheduler.last_future`; `tests/unit/logic/workflows/test_refinery_engine.py:1259-1274`
  assigns it directly and must keep passing unmodified.

### 3. `process_single_article` stage split (attempt in this phase)

Only mechanical extraction is allowed: private methods on `RefineryEngine`,
same class, same closure semantics, no behavior change. The candidate seams, in
order:

- `_attempt_publishing_recovery(article_id, article, run) -> bool` (True =
  recovered, caller returns immediately; stores `run.numeric_id` once for the
  later publishing mark)
- `_resolve_identity(article_id, article, posts_dir, run) -> PublicationIdentity`
  (records `identity_resolved` and stores the locked filename/slug on the run)
- `_resolve_article_image(article, article_id, identity, target_dir, run)`
  (keeps the `self._download_image` hook; returns `bool`)
- `_refine_article(article, article_id, canonical_date, run)`
  (`editor.process_article` + `ValueError` branches; returns
  `(refined_content, grounding_notes)` or `None` when blocked)
- `_enforce_publication_gates(article_id, refined_content, identity, run)`
  (policy gate + frontmatter guard + `register_slug`)
- `_publish_to_target_repo(*, ..., run) -> bool` (branch → write → frontend
  validation → commit/push → PR; stores `branch_name`/`pr_url`/validation path
  on the run holder and returns success)

State shared by the stages lives on a private `_PublicationRun` holder instead
of closures:
`record_stage` still appends `PublicationAttemptStageResult` (same
`None`-filtering) and mirrors the list to `engine._last_publication_stages`;
`persist_attempt` still routes through
`engine._persist_publication_attempt_summary` so test patches keep
intercepting.

Accepted difference (reviewed): `AuditScheduler` captures the db manager at
construction, whereas the original engine read `self.db` per call. No
production or test caller reassigns `RefineryEngine.db` after construction, so
the observable behavior is unchanged; recorded here instead of adding a
per-call db parameter for a seam nobody uses.

If any extraction requires passing more than ~8 parameters or reordering
stage recording / `persist_attempt` calls, STOP and defer that seam to 7b —
partial mechanical splits are acceptable; a semantic rewrite is not.

### Test plan

- New `tests/decompose_refinery/test_publication_attempts.py`:
  - `artifact_name` sanitization (unicode/punctuation/empty → `unknown`).
  - `persist_publication_attempt` writes the canonical JSON with every passed
    field; `read_publication_attempt` round-trips it.
  - `persist_interrupted_attempt` refuses to overwrite a prior `success: true`
    file; writes when absent; tolerates missing dir? (dir is created by the
    caller/engine — keep the store's contract explicit and test it).
  - corrupt JSON read → `None`.
- New `tests/decompose_refinery/test_audit_scheduler.py`:
  - backpressure skip records `audit_skipped_backpressure` via the injected
    recorder and does not submit.
  - submit failure records `audit_failed` (`submission_failed: …`).
  - callback success maps status/reason/attempts/timeout/model/endpoint.
  - callback crash records `audit_failed`; non-dict result records
    `invalid_audit_result_type:<type>`.
  - `record_status` no-ops on missing id / missing db method / raises inside db.
- Existing suites (250 tests) stay green **without edits**; the engine
  delegates exist precisely so the current patch points (`engine.executor`,
  `engine.auditor`, `engine._record_audit_status`,
  `engine.publication_attempts_dir`, `RefineryEngine._safe_publication_artifact_name`)
  keep working. Any existing test that must change is a STOP-and-report signal
  unless the spec explicitly allows it.

## Steps

### Step 0: Baseline + drift check

Run the baseline command in "Current state" and the drift check in the header.
On any non-green result or in-scope drift: STOP and report.

**Verify**: 250 passed; drift check clean.

### Step 1: `publication_attempts.py` + tests

1. Write the new module (verbatim moves; keep comments that carry behavior
   contracts — e.g. "never overwrites a successful attempt").
2. Write `tests/decompose_refinery/test_publication_attempts.py` first against
   the module API (TDD), then make it pass.
3. Rewire the engine: keep `self.publication_attempts_dir`,
   `_safe_publication_artifact_name` (static delegate),
   `_persist_publication_attempt_summary` (delegate reading
   `self.publication_attempts_dir` at call time), `_persist_interrupted_attempt`
   (delegate). Delete the moved bodies.
4. Rewire `publication_run_workflow._read_attempt_for_id` →
   `read_publication_attempt(self._attempts_dir, resolved_id)` and drop its
   `RefineryEngine` import; reword the docstring to name the new module.
5. Rewire `pipeline_e2e.py:914` → `artifact_name(...)`.

**Verify**: `make lint` exit 0; targeted suites 250 passed + new tests pass;
`grep -rn "RefineryEngine" news_collector/logic/workflows/publication_run_workflow.py`
→ no matches.

### Step 2: `audit_scheduler.py` + tests

1. Write `tests/decompose_refinery/test_audit_scheduler.py` against the API.
2. Implement the scheduler (verbatim move; keep every log string).
3. Rewire the engine: `self.audit_scheduler = AuditScheduler(self.db)`, delete
   `_last_audit_future` and `_schedule_optional_audit`'s body, keep the two
   delegates with call-time injection.

**Verify**: targeted suites green (especially
`tests/integration/test_refinery_audit_staging.py` and
`tests/unit/logic/workflows/test_refinery_engine.py` audit tests); `make lint`
exit 0.

### Step 3: `process_single_article` stage split (mechanical only)

Apply the seams from Design §3 one at a time, running the targeted suites after
each; stop at the first seam that would need a semantic change and record it in
`todo.md` as deferred-to-7b.

**Verify**: targeted suites green; `git diff` on `process_single_article`
contains only moved lines (no reordered `record_stage`/`persist_attempt`
calls).

### Step 4: Full gates + docs

1. `make lint && make type && make test && make test-boundaries` → exit 0.
2. Update `docs/ARCHITECTURE.md` §"RefineryEngine is still too broad": name the
   extracted modules and the remaining deferred seams.
3. Update `docs/dev/source-of-truth-backlog.md`: mark the stale recommendation
   resolved and point at plan 060 Phase 7 with the remaining 7b scope.
4. Annotate `plans/060/todo.md` Phase 7's first two checkboxes with what
   landed and what remains.
5. `.venv/bin/python scripts/validate_plans_ledger.py` → OK (unchanged ledger).

**Verify**: all commands exit 0; diff limited to in-scope files.

## Done criteria (machine-checkable)

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0
- [ ] `publication_attempts.py` and `audit_scheduler.py` exist; the engine no
      longer contains their logic (only delegates)
- [ ] `publication_run_workflow.py` has no `RefineryEngine` import
- [ ] No existing test was edited to accommodate the refactor (new tests only)
- [ ] `git diff --name-only` lists only in-scope files
- [ ] Docs/backlog/plan checkboxes reconciled; ledger validator OK

## STOP conditions

Stop and report (do not improvise) if:

- The drift check or baseline is not clean.
- Any extraction forces a JSON shape, stage order, log-string, or return-shape
  change.
- An existing test must be modified to keep passing (other than the explicit
  rewire of `publication_run_workflow`/`pipeline_e2e` production call sites).
- `engine.publication_attempts_dir` reassignment or `engine.executor`
  injection stops working.
- Any step's verification fails twice after a reasonable fix attempt.

## Git workflow

- Branch (backend): `advisor/060-phase-7a-refinery-recording-audit`.
- Commits: `refactor(workflows): extract publication attempt recording`,
  `refactor(workflows): extract optional audit scheduler`,
  `refactor(workflows): split publication stages` (if Step 3 lands).
- Do NOT push or open a PR unless the operator instructed it.
