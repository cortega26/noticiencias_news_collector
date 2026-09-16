# Plan 106: Extract the publication process-mode pipeline out of the legacy UI entrypoint

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/publication_run_workflow.py apps/refinery/main.py news_collector/logic/workflows/refinery_engine.py news_collector/logic/workflows/manual_ingest.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (plan 095 Step 2 landed: the allowlist helper lives in `logic/workflows/published_content_utils.py`; this plan does not touch it)
- **Category**: tech-debt
- **Planned at**: commit `60f0673`, 2026-09-16

## Why this matters

`PublicationRunWorkflow._run` (the serving-dispatched publish path) imports
`apps.refinery.main.main` — the legacy Streamlit entrypoint — so the serving
stack transitively depends on UI code, blocking `apps/refinery` removal. Plan
095 proved the direct route is a trap: `main()` process-mode owns ~400 lines of
glue with no workflow-layer equivalent (manual-ingest wiring, export
selection incl. the plan-071 wrong-article guard, source/target clones, LLM
preflight + error shapes, git user config, result merge), and porting it into
`publication_run_workflow.py` would duplicate correctness-critical logic that
already drifted once. The non-duplicating route, specified here: extract the
glue ONCE into a workflow-layer module both callers share, with the UI
entrypoint delegating to it. After this plan, no workflow imports `apps.*` and
no behavior is duplicated or dropped.

## Current state

Prior investigation (plan 095 Step 1, committed branch, re-verify every claim
below before relying on it):

- `news_collector/logic/workflows/publication_run_workflow.py:~229`: `from apps.refinery.main import main as run_refinery`, called with `process_id`/`article_url`/`skip_visuals=False`; `result` dict feeds `self.complete`/`self.fail` (`:240-254`); own `DatabaseManager` semantics documented in the comment (never the serving singleton); blocking on a daemon thread.
- `apps/refinery/main.py::main()` process-mode stage list (re-verify line numbers, they shift): config load → preflight (`llm_preflight_failed` shape, ~:495-514) → own `DatabaseManager` → engine build → `ManualUrlIngestService.ingest` for `article_url` (`~:556-579`, feeds the `article_id` merge `_collect_publication_summary` depends on) → source clone freshness (`_safe_clone_source_repo`, ~:93) → collector skip → export selection (`_select_export_articles`, ~:324) → export load (`_load_export_articles`, ~:171, incl. plan-071 guard + adapter wiring + in-flight check) → file fallback scan (~:665-717) → target clone + git user config (~:758-779) → `engine.process_articles` → result merge.
- `news_collector/logic/workflows/target_repo_writer.py` no longer imports `apps.refinery` (095 Step 2 landed); the remaining `serving/api.py → apps.refinery` imports (analytics read-model, content snapshot, `run_bulk`) are out of scope — list, don't touch.

Repo conventions that apply here:

- LAW-B3: orchestration composes collaborators — the new module is orchestration (moves existing glue, authors no new rules).
- LAW-B9: a new module needs proof — the proof is two callers (`main.py` + `publication_run_workflow.py`) sharing ~400 lines that cannot live in either.
- No behavior change is the requirement: same stages, same order, same `result` shape, same DB-manager ownership, same blocking semantics.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |
| Refinery  | `make test-refinery`     | declared   | 8 passed + 2 KNOWN environmental failures (see below) |

Known pre-existing `test-refinery` failures (verified identical on pristine base `60f0673` in a scratch worktree, 2026-09-16): `test_second_rerun_reuses_cache_and_does_not_requery` + `test_manual_refresh_button_forces_a_fresh_query` fail with empty-URL `git clone` (no credentials in sandbox). If your run shows exactly these 2 (and no others), that is the baseline, not a regression — prove it the same way (scratch worktree at the merge-base, same command) before claiming it.

## Scope

**In scope** (the only files you should modify):

- NEW `news_collector/logic/workflows/publication_pipeline.py` (the extracted process-mode pipeline)
- `apps/refinery/main.py` (delegate process-mode to the new module; behavior identical)
- `news_collector/logic/workflows/publication_run_workflow.py` (call the new module instead of `apps.refinery.main`)
- `tests/unit/logic/workflows/test_publication_run_workflow.py` (+ new test file if cleaner) — dispatch tests incl. a no-`apps.refinery`-import test

**Out of scope** (do NOT touch, even though they look related):

- Engine, editor, auditor, git publisher, adapters, contracts — stage internals move verbatim or not at all.
- `serving/api.py → apps.refinery` imports — separate future plans.
- `apps/refinery/admin_panel.py`, Streamlit behavior — the UI keeps working through delegation; `make test-refinery` proves it.
- Retrying the 095 approach (duplicating glue into the run workflow) — explicitly rejected; shared module or nothing.

## Git workflow

- Branch: `advisor/106-publication-pipeline`
- Conventional commits, e.g. `refactor(workflows): extract publication process-mode pipeline`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. Record `make test-refinery`'s exact outcome (expect 8 passed + the 2 known environmental failures). On any OTHER `declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: baselines recorded, including the refinery pair.

### Step 1: Re-verify the 095 inventory (no edits yet)

Re-derive from the live code (do NOT trust this plan's line numbers blindly):

1. The full `main()` process-mode stage list with current file:line for each stage.
2. Every consumer of the `result` dict shape (`complete`/`fail`/`_collect_publication_summary`).
3. Every importer of `main` and of `run_refinery`.
4. The plan-071 guard's exact location + wording (it must move verbatim).

**Verify**: written inventory. If ANY stage has no workflow-layer home and cannot move verbatim (Streamlit-session dependency, UI state), STOP and report — the extraction premise is broken.

### Step 2: Extract the pipeline module

Create `news_collector/logic/workflows/publication_pipeline.py` with ONE entry point (e.g. `run_publication_pipeline(...)`) that owns the inventoried stages verbatim: same order, same DB-manager ownership (own manager, never serving's), same blocking behavior, same `result` dict keys, same error shapes (`llm_preflight_failed`, plan-071 guard text, no-article message). Move code, don't rewrite it; adjust only imports and the function boundary. No new policy, no new thresholds, no new error types.

**Verify**: `make lint` → exit 0; module imports standalone (no `apps.*`, no Streamlit — grep).

### Step 3: Rewire both callers

1. `apps/refinery/main.py`: process-mode path delegates to the new entry point (thin: argument mapping only). All other modes untouched.
2. `publication_run_workflow.py::_run`: calls the new entry point instead of importing `apps.refinery.main`. The `_transition`/`_heartbeat_loop`/`complete`/`fail` surrounding logic stays identical.
3. `grep -rn "from apps.refinery\|from apps import\|import apps.refinery" news_collector/logic/workflows/` → no matches (comments/docstrings updated too).

**Verify**: grep clean; `make lint` → exit 0.

### Step 4: Tests

1. Dispatch tests: success path (mock the pipeline entry point at the module boundary — assert called with `process_id`/`article_url`, `complete` vs `fail` on `result` shapes) + no-`apps.refinery`-import test (block `apps.refinery.main` via `sys.modules` patch and run the success path, following repo module-patch patterns).
2. Equivalence tests for the moved glue where cheap (plan-071 guard behavior, preflight error shape) — port, don't reinvent.
3. `make test-refinery`: must show EXACTLY the Step-0 baseline (8 + same 2 environmental). Any new failure or any previously-failing test now passing-for-the-wrong-reason → investigate, don't hand-wave (prove via the scratch-worktree comparison from the command table).

**Verify**: new tests pass; refinery outcome identical to baseline, proven by comparison.

### Step 5: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0 (modulo the known flake signature only).

## Test plan

- New dispatch + no-UI-import + ported equivalence tests.
- Existing collection/publication workflow suites green (behavior preservation).
- `make test-refinery` identical-to-baseline, proven by scratch-worktree comparison.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0
- [ ] No `apps.*` import remains under `news_collector/logic/workflows/` (grep, incl. comments)
- [ ] `make test-refinery` outcome identical to the Step-0 baseline (proven by comparison, not asserted)
- [ ] New dispatch/equivalence tests exist and pass
- [ ] `git diff --name-only <base>...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts/inventory.
- Any stage would be lost, reordered, or reworded in translation (report the gap with file:line).
- The `result` dict shape needs ANY change to fit the new module (report; don't adapt callers silently).
- `make test-refinery` diverges from baseline in either direction without a proven cause.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- The new module is THE owner of publish-dispatch glue; future `main.py`/`serving` dispatch changes go through it. The remaining `serving/api.py → apps.refinery` imports are separate plans.
- When the Streamlit panel is retired, `main.py`'s delegation (not the pipeline) is what gets deleted — say so in the module docstring.
- Reviewers: diff each moved stage against its origin line-by-line; a dropped log line is acceptable, a dropped behavior is not.
- **Deferred:** `serving/api.py`'s three `apps.refinery` imports — same decoupling theme, separate plans.
