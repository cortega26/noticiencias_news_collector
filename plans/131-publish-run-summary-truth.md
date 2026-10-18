# Plan 131: Publish-run summaries must not report a previous attempt's PR evidence

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/logic/workflows/publication_attempts.py news_collector/logic/workflows/publication_run_workflow.py news_collector/serving/api.py news_collector/logic/workflows/publication_pipeline.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW-MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`publication_attempts/{article_id}.json` is keyed **per article**, not per run.
`_collect_publication_summary` reads that file by article id and copies
`pr_url`, `branch_name`, `final_slug`, `failure_class`, `success` and `stages`
into the run summary whenever they are non-`None`. So a run that produced no
attempt evidence of its own — a no-op (article left the export shortlist), a
crash before any stage persisted, or a batch item that failed — inherits the
**previous** attempt's PR URL and `success: true`. The operator's review loop
(`/v1/admin/quality/recent` → `apps/admin` quality page) then shows "PR ↗" and a
successful-looking run for something that failed, and the batch item list
carries a `pr_url` for a `failed` item. Publishing identity and per-item
outcomes are load-bearing here (LAW-B6: batch workflows must report per-item
outcomes; a run summary is that report).

## Current state

Files and roles:

- `news_collector/logic/workflows/publication_attempts.py` — writes/reads the
  canonical attempt artifact; `artifact_name(article_id)` at `:56-59` and
  `_summary_path()` at `:62-63` (per-article path, **no run token**).
  `persist_interrupted_attempt` at `:110+` deliberately keeps a prior
  `success: true` file (`_has_successful_attempt` guard).
- `news_collector/logic/workflows/publication_run_workflow.py` — the run
  orchestrator. `_collect_publication_summary` at `:470-505` merges the attempt
  fields into the summary; its docstring claims it "never fall[s] back to
  'newest file in the dir'" — true, but the per-article file is still a
  previous run's file. The orchestrator has a run id (`PublicationRunRequest.run_id: int`
  at `:74`; the persisted workflow row id is threaded through `_run_publication`
  / `_run_publication_batch` at `:259-281`).
- `news_collector/serving/api.py:1888-1890` — serves `pr_url=summary.get("pr_url")`
  on the run-status payload.
- `apps/admin/src/pages/quality.astro:95-99` — renders the PR link whenever
  `run.pr_url` is set, before the failure badge.

Current excerpt (`publication_run_workflow.py:481-499`):

```python
        attempt = self._read_attempt_for_id(resolved_id) if resolved_id else None
        if attempt:
            for key in (
                "pr_url",
                "branch_name",
                "final_slug",
                "output_filename",
                "failure_class",
                "success",
                "target_repo",
            ):
                if attempt.get(key) is not None:
                    summary[key] = attempt[key]
            summary["stages"] = attempt.get("stages", [])
```

Conventions to match: workflow code is orchestration — no policy here; keep the
change mechanical and typed. Error handling follows LAW-B7 (structured results,
no bare `except Exception: pass`). Test convention: `tests/unit/logic/workflows/`
mirrors the module path (see `tests/unit/logic/workflows/test_publication_run_workflow.py`).

## Commands you will need

| Purpose          | Command                                                        | Provenance | Expected on success              |
|------------------|----------------------------------------------------------------|------------|----------------------------------|
| Install/baseline | `make bootstrap`                                               | declared   | exit 0                           |
| Lint             | `make lint`                                                    | declared   | exit 0                           |
| Types + coverage | `make type`                                                    | declared   | exit 0, ratchet OK               |
| Unit suite       | `make test`                                                    | declared   | all pass                         |
| Boundaries       | `make test-boundaries`                                         | declared   | exit 0                           |
| Focused tests    | `.venv/bin/pytest tests/unit/logic/workflows/ -q --no-cov`     | declared   | all pass                         |
| Ledger           | `make plans-ledger-check`                                      | declared   | `validate_plans_ledger: OK`      |

Provenance note: the advisor did not run the test suite or `make` gates (read-only
rule); all `declared` rows come from the `Makefile` and CI config. A `declared`
command that fails on an **unmodified** checkout is a broken baseline — STOP and
report, do not repair it.

## Scope

**In scope**:

- `news_collector/logic/workflows/publication_attempts.py`
- `news_collector/logic/workflows/publication_run_workflow.py`
- `tests/unit/logic/workflows/test_publication_run_workflow.py` (or a new
  `test_publication_attempts_freshness.py` in the same directory)

**Out of scope** (do NOT touch):

- `news_collector/serving/api.py` and `apps/admin/**` — the payload shape stays
  as-is; the fix is upstream. Verify only.
- `publication_pipeline.py` — its own plan (133) touches the clone path.
- The `success` semantics of `PublicationAttempt` itself.

## Git workflow

- Branch: `advisor/131-publish-run-summary-truth`
- One commit per step or per logical unit; conventional commits, e.g.
  `fix(publication): key attempt evidence by run id (plan 131)` — see recent
  history (`fix(publication): correlate callbacks to exact attempts`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining commands in the table **on the
unmodified checkout**. Record the results. Red baseline → STOP (see the
instructions above).

**Verify**: every table command runs and matches its expected result.

### Step 1: Stamp the attempt artifact with the run that wrote it

In `publication_attempts.py`:

1. Add a `run_id: int | None = None` field to `PublicationAttempt`.
2. Include it in the persisted JSON in `persist_publication_attempt` (the
   summary object it writes). Keep the filename unchanged (`{article_id}.json`)
   — other readers use it.
3. Do the same for the interrupted-attempt path if it serializes fields
   explicitly.

Then in `publication_run_workflow.py`:

4. Thread the current run id into the attempt writes performed by the publish
   call for this run (the same `run_id` used at `:259-281`). If the attempt is
   persisted deep inside the pipeline and the run id is not reachable there,
   STOP and report — do **not** invent a global.

**Verify**: `grep -n "run_id" news_collector/logic/workflows/publication_attempts.py` →
the new field appears; `.venv/bin/pytest tests/unit/logic/workflows/ -q --no-cov` → all pass.

### Step 2: Make the summary reader require this run's evidence

In `_collect_publication_summary` / `_read_attempt_for_id`
(`publication_run_workflow.py:479-505`):

5. Read the attempt only when it belongs to the current run. Preferred rule:
   `attempt.get("run_id") == current_run_id`; if the persisted artefact carries
   no `run_id` (legacy files written before this change), treat it as **not
   this run's evidence** and do not merge it.
6. If the current run id is not reachable at that call site, fall back to the
   documented alternative: require `generated_at` to be later than the run's
   `started_at` (the workflow row already stores it). Pick one rule and state
   it in the docstring; do not implement both.
7. Update the docstring to describe the real rule (it currently explains only
   the "newest file" hazard).

**Verify**: `.venv/bin/pytest tests/unit/logic/workflows/ -q --no-cov` → all pass;
`grep -n "run_id" news_collector/logic/workflows/publication_run_workflow.py | sed -n '1,20p'` → the merge is gated.

### Step 3: Assert the consumers still behave

8. Confirm `serving/api.py:1888-1890` needs no change (it reads `summary`), and
   that `apps/admin/src/pages/quality.astro` renders "no PR" when `pr_url` is
   absent (read the file; if it hides the cell already, no change).

**Verify**: `grep -n "pr_url" apps/admin/src/pages/quality.astro` → the guard is visible in your report.

## Test plan

New tests in `tests/unit/logic/workflows/` (model after the existing
`test_publication_run_workflow.py` fixtures — real temp dirs via `tmp_path`,
no network, mocked only at the git/LLM edge):

- **Regression (the bug)**: pre-write a *successful* attempt file for article X
  (with a different run id / older `generated_at`), then run a publish path for X
  that persists nothing (no-op) → assert `summary["pr_url"] is None` and
  `summary["success"] is not True`.
- **Happy path**: a run that persists its own attempt → the summary carries
  *this* run's `pr_url`, `final_slug`, `stages`.
- **Legacy file**: an attempt file with no `run_id` key → not merged.
- **Interrupted re-publish**: `persist_interrupted_attempt` after a prior
  success → the prior file is still kept for history, but the new run's summary
  does not claim its PR.

**Verify**: `.venv/bin/pytest tests/unit/logic/workflows/ -q --no-cov` → all pass,
including the new tests; `make test` → green.

## Done criteria

All must hold:

- [ ] `make lint` exits 0
- [ ] `make type` exits 0 (coverage ratchet unchanged)
- [ ] `make test` exits 0; the new regression test fails on `git stash`-ed
      original code (prove it once and say so in the ledger row)
- [ ] `make test-boundaries` exits 0
- [ ] `git diff --name-only main...HEAD` lists only the in-scope files
- [ ] `plans/README.md` row for 131 updated (status + one-line evidence)
- [ ] `make plans-ledger-check` prints `validate_plans_ledger: OK`

## STOP conditions

- The excerpts above do not match the live code (drift).
- The run id is not reachable at the attempt-persistence site and no
  `started_at` is available for the fallback rule → report, do not invent state.
- A step's verification fails twice after a reasonable repair attempt.
- The fix appears to require touching `serving/api.py` or the admin app.

## Maintenance notes

- If a future change renames the attempt artifact or adds a second consumer,
  the run-id match must move with it — grep `publication_attempts` for readers.
- Reviewer should scrutinise: legacy-file behaviour (must be "ignore", never
  "trust"), and that no path silently writes an attempt for a *different*
  article id.
- **Deferred:** surfacing "evidence absent" as an explicit field on the admin
  payload (so a no-op run reads as "no attempt recorded" rather than blank).
  Unblocked by nothing; it just wasn't needed for correctness.
