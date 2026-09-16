# Plan 095: Break the workflow → legacy-UI dependency (workflows must not import `apps.refinery`)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/target_repo_writer.py news_collector/logic/workflows/publication_run_workflow.py apps/refinery/published_content.py apps/refinery/main.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

Core workflow code imports the legacy Streamlit app layer, inverting the
documented dependency direction (edges depend inward; `apps/refinery` must not
be a dependency of workflows): `target_repo_writer.py` imports a helper from
`apps.refinery.published_content`, and — worse — the serving-dispatched
`PublicationRunWorkflow._run` imports `apps.refinery.main.main` (the legacy UI
entrypoint) on its publication path. The serving stack therefore transitively
depends on Streamlit-app code, blocking removal/extraction of the legacy panel
and forcing `test-boundaries` to reason about UI imports. After this plan,
workflows depend only inward.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/target_repo_writer.py` — imports the UI helper (line 25), calls it (line 100)
- `news_collector/logic/workflows/publication_run_workflow.py` — imports the UI entrypoint inside `_run` (line 229)
- `apps/refinery/published_content.py` — current home of the helper
- `apps/refinery/main.py` — current home of `main()`

Excerpts of the code as it exists today:

`target_repo_writer.py:25,100`:

```python
from apps.refinery.published_content import prune_hero_placeholder_allowlist_for_post
...
if prune_hero_placeholder_allowlist_for_post(target_dir, target_file_path):
```

`publication_run_workflow.py:228-239`:

```python
try:
    from apps.refinery.main import main as run_refinery

    # `main()` in process_id mode skips the collector and uses its
    # own DatabaseManager — it never touches the serving singleton.
    # It is blocking (runs its own asyncio loop internally); fine on
    // this daemon thread, same as CollectionRunWorkflow._run.
    result = run_refinery(
        process_id=str(article_id) if article_id is not None else None,
        article_url=article_url,
        skip_visuals=False,
    )
```

(Note: the reverse edges also exist — `apps/refinery/main.py:32` imports the
engine — so this is a genuine cross-boundary cycle, not a one-way slip.)

Repo conventions that apply here:

- ARCHITECTURE.md dependency direction: ingestion/UI edges depend inward;
  `apps/refinery` must not become a dependency of workflows (or a second
  contract-definition layer).
- LAW-B3: orchestration composes collaborators — dispatch through the workflow
  class, not the app `main`.
- Test gates: `make test-boundaries` + refinery decomposition tests
  (`tests/decompose_refinery/`) pin the seams you will touch.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |
| Refinery  | `make test-refinery`     | declared   | all pass (legacy panel still works) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/target_repo_writer.py` (import swap only)
- New home of the moved helper: `news_collector/logic/workflows/published_content_utils.py` (create) — or `storage/` if the helper turns out to be DB-coupled; decide in Step 1 and record why
- `apps/refinery/published_content.py` (re-export shim from the new home — do NOT break existing UI importers)
- `news_collector/logic/workflows/publication_run_workflow.py` (dispatch change)
- `tests/unit/logic/workflows/test_publication_run_workflow.py`, `test_collection_run_workflow.py` (update/extend)

**Out of scope** (do NOT touch, even though they look related):

- `apps/refinery/main.py` and `admin_panel.py` behavior — UI keeps working via the shim.
- `news_collector/serving/api.py` imports of `apps.refinery.*` (analytics read-model, content snapshot, bulk_helper) — same disease, separate plans; report them, don't expand.
- Removing the `apps/refinery` package — explicitly blocked until the Astro app is confirmed flawless.

## Git workflow

- Branch: `advisor/095-workflow-ui-decoupling`
- Conventional commits, e.g. `refactor(workflows): stop importing legacy UI layer`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Characterize both edges before moving anything

1. Read `prune_hero_placeholder_allowlist_for_post` in full: its imports, its I/O
   (target_dir files? DB? Streamlit state?). Record every module it touches.
   If it imports Streamlit or UI state, STOP and report — the move needs a split, not a relocation.
2. Read `apps/refinery/main.py main()` `process_id`/`article_url` mode end to end:
   list every stage it runs (collector skip? engine? git? DB manager whose?).
   Compare against what `PublicationRunWorkflow` needs (single article publish → summary dict).
3. `grep -rn "prune_hero_placeholder_allowlist_for_post\|from apps.refinery.main import" news_collector/ apps/ scripts/ tools/ tests/ | grep -v __pycache__` — full importer list for both.

**Verify**: written inventory (in your final report + commit message): helper's dependency surface; `main()` process-mode stage list; all importers. If the helper is UI-coupled OR `main()` process-mode does work with no workflow-layer equivalent (e.g. Streamlit-session setup), STOP — report which, with file:line.

### Step 2: Relocate the helper (mechanical)

1. Move `prune_hero_placeholder_allowlist_for_post` verbatim to the new module.
2. `target_repo_writer.py` imports from the new home.
3. `apps/refinery/published_content.py` keeps `from <new_home> import prune_hero_placeholder_allowlist_for_post` so UI importers are untouched.
4. Run `make test-refinery` to prove the legacy panel still resolves the helper.

**Verify**: `grep -rn "from apps.refinery" news_collector/logic/workflows/target_repo_writer.py` → no matches; `make test-refinery` → pass.

### Step 3: Dispatch through the workflow layer, not the app `main`

Replace the `from apps.refinery.main import main as run_refinery` call in
`PublicationRunWorkflow._run` with a direct call into the workflow/engine
collaborator that `main()` process-mode itself delegates to (identified in
Step 1 — likely `RefineryEngine` + summary collection already present via
`self._collect_publication_summary`).

Constraints (all must hold, else STOP and report):

- Same `DatabaseManager` semantics the comment documents (own manager, never the serving singleton).
- Same blocking/asyncio behavior on the daemon thread.
- Same `result` dict shape consumed by `self.complete`/`self.fail` below (lines 240-254) — no change to status-transition logic.
- `CollectionRunWorkflow` untouched.

**Verify**: `tests/unit/logic/workflows/test_publication_run_workflow.py` + `test_collection_run_workflow.py` green; add a test asserting `_run` never imports `apps.refinery.main` (e.g. block the module via `sys.modules` patch and run the success path, or assert no such import string executes — simplest: `assert "apps.refinery" not in sys.modules` after a dispatched run in an isolated test, following the repo's existing module-patch patterns).

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries && make test-refinery` → all exit 0. Final: `grep -rn "from apps.refinery\|from apps import\|import apps.refinery" news_collector/logic/workflows/` → no matches (except comments/docstrings, which you must also update if they reference the old structure).

## Test plan

- Existing workflow/run tests (collection + publication) — behavior preservation.
- New no-UI-import test for the publication dispatch path.
- `make test-refinery` — legacy panel characterization suite still passes via the shim.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-refinery` all exit 0
- [ ] No `apps.refinery` import remains under `news_collector/logic/workflows/` (grep)
- [ ] UI importers of the moved helper still work (shim + refinery suite green)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 shows the helper is UI-coupled or `main()` process-mode has no workflow-layer equivalent.
- Any `main()` behavior (retries, visual skips, DB choice) would be lost in translation — report the gap instead of approximating.
- The remaining `serving/api.py → apps.refinery` imports tempt scope expansion — list them in the report, do not touch them.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- The new helper module's owner is the workflow layer; future allowlist logic goes there, and the `apps.refinery` shim is deleted when the Streamlit panel is retired (link this plan in that future cleanup).
- Reviewers: diff `main()` process-mode against the new dispatch line-by-line; a dropped stage here silently changes publication semantics.
- **Deferred:** `serving/api.py`'s three `apps.refinery` imports (analytics read-model, content snapshot, bulk_helper) — same recipe, separate plans; bulk_helper's is the most entangled (bulk-reset endpoint owns its own copy of the cap logic after plan 085 — coordinate).
