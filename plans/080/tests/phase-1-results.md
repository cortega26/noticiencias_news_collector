# Plan 080 — Phase 1 results

Recorded 2026-09-14.

## Deliverable

`tests/property/test_workflow_lifecycle_stateful.py` (new file):

- `WorkflowLifecycleMachine(RuleBasedStateMachine)` — one machine exercising
  both `CollectionRunWorkflow` and `PublicationRunWorkflow` against one
  isolated, machine-owned SQLite database (`TemporaryDirectory` +
  `DatabaseManager` + `Base.metadata.create_all`), a controlled clock
  (`_Clock`, patched into each workflow module's own `datetime` binding via
  `pytest.MonkeyPatch`), and no-op `_dispatch` on both instances. Exported as
  `TestWorkflowLifecycle = WorkflowLifecycleMachine.TestCase` with
  `settings(max_examples=20, stateful_step_count=20, deadline=None, derandomize=True, database=None)`.
  Measured at ~1.8-2s for 20 examples x 20 steps — comfortably inside the
  repository's global 10s pytest timeout, so no test-local timeout override
  was needed (the spec's remedy for exceeding 10s does not apply here).
  The expected-state model (`self.model`) and the recovery predicate
  (`_is_stale_running`) are independently re-derived from
  `01-stateful-workflows.md` / the workflow modules' own docstrings; neither
  calls or inspects `recover_expired_leases()` to decide an expected answer.
- 6 deterministic (non-Hypothesis) boundary tests at 59/60/61 seconds:
  `test_collection_expiry_boundary_is_strict`,
  `test_publication_expiry_boundary_is_strict`, and
  `test_null_heartbeat_uses_started_at_with_the_same_strict_boundary`, each
  `@pytest.mark.parametrize`d over `[(59, False), (60, False), (61, True)]`
  (3 cases x 3 tests = 9 test items). These also patch a frozen clock into
  the relevant workflow module — an earlier version used real wall-clock
  `datetime.now()` and was flaky/wrong exactly at the 60s case, because real
  time elapsed between capturing `now` in the test and the workflow's own
  internal `datetime.now(timezone.utc)` call a moment later shifted the
  cutoff by a few milliseconds. This was caught before drawing any
  conclusion from it; it is a test artifact, not a production defect.

10 test items total in the new file (1 stateful `TestCase` + 9 parametrized
boundary cases).

No changes were made to the two existing unit test files
(`tests/unit/logic/workflows/test_collection_run_workflow.py`,
`tests/unit/logic/workflows/test_publication_run_workflow.py`) — the machine
did not discover a production defect requiring a minimized regression there.

## W1-W5 acceptance evidence

**W1 — Single active row.** Enforced by the `@invariant() database_matches_model`
method, which runs after every rule step (init + 20 steps x 20 examples). For
each of `collection`/`publication` it asserts at most one row with
`status in ("queued", "running")` exists in the database, independently of
the model, on every step of all 20 examples. Also implicitly exercised by
`start_collection`/`start_publication`, which assert `already_running` with
the correct existing id whenever the model's own `_active_id` lookup (which
itself asserts `len(active) <= 1`) finds one. Both a collection row and a
publication row are allowed to be active simultaneously — verified by the
per-run-type scoping of every check (never a single combined check across
both types). Passed across all 20 generated examples (`derandomize=True`,
fixed seed via Hypothesis's own derandomized examples).

**W2 — Expiry boundary.** `_is_stale_running` encodes `heartbeat_at < cutoff`
(strict) and, for NULL heartbeat, `started_at < cutoff` (strict) — equality
is fresh. Proven two ways:
1. The 9 deterministic parametrized tests above: 59s and 60s never recover,
   61s always recovers, for collection running+heartbeat, publication
   running+heartbeat, and collection running+NULL-heartbeat (using
   `started_at`). All 9 passed.
2. The stateful machine's `advance_clock` rule draws explicitly from
   `[0, 1, 59, 60, 61, 120]` (not left to arbitrary Hypothesis integers), so
   every generated example has a real chance of landing exactly on the
   boundary during `recover_during_service`/`simulate_boot` calls; the
   invariant caught nothing across 20 examples.

**W3 — Queued safety.** `start_collection`/`start_publication` never call
`recover_expired_leases(include_queued=True)` — they replicate production's
own `include_queued=False` call before checking for an active row, so a
second live `start()` cannot reap a queued row (mirrored exactly in
`_apply_expected_recovery(..., include_queued=False)`). `simulate_boot`
calls `include_queued=True` (default), matching production's boot-time
recovery, and the model independently predicts which queued rows become
`interrupted`. `test_start_leaves_fresh_queued_row_alone` and
`test_start_leaves_fresh_unbeaten_running_row_alone` in the existing unit
test files (Plan 078 regressions, re-run unmodified as part of Phase 1's
verification block) cover the same invariant directly. All passed.

**W4 — Terminal stability.** `heartbeat_run`/`complete_run`/`fail_run` draw
an arbitrary known run id (via `st.data()` + `sampled_from(sorted(self.model))`)
every time, not just active ones — this naturally and repeatedly exercises
"repeat operation on an already-terminal row" across all 20 examples, and
each rule asserts the operation returns `False`/no-op unless the model says
the row is currently `running`. Request-metadata preservation
(`_assert_request_metadata_preserved`) is checked immediately after every
successful `complete`/`fail`, reading the row back and confirming the
original request fields (`dry_run` / `article_id`) written by `start()`
survive alongside the merged `summary`. Both run types are proven isolated
by construction: every rule that mutates state looks up `rec["run_type"]`
and dispatches to the matching workflow instance only, and the invariant
checks `run_type` per row against the model on every step.

**W5 — Test isolation and sensitivity.**
- Isolation: each machine instance owns its own `TemporaryDirectory`,
  `DatabaseManager`, and `pytest.MonkeyPatch()` instance;
  `teardown()` undoes the monkeypatch, closes the manager, and removes the
  temp dir, called by Hypothesis even on assertion failure. No thread,
  network, or production DB/log/cache path is touched (SQLite files live
  under the machine's own `TemporaryDirectory`).
- Sensitivity (mutation check): `news_collector/logic/workflows/collection_run_workflow.py`
  was hashed (`sha256sum`) before any change
  (`8e9980c4fdfab6c5a48136bd61453b79e6830cdc80ca51a76b2f5bbfc1a166aa`), then
  `recover_expired_leases`'s `WorkflowRun.heartbeat_at < cutoff` was changed
  to `<= cutoff` (one comparison flip). Re-running
  `tests/property/test_workflow_lifecycle_stateful.py` immediately failed:
  `test_collection_expiry_boundary_is_strict[60-False]` — `assert (1 in [1]) is False`
  (1 failed, 9 passed). The edit was then reverted with `Edit` (not `git
  checkout`/`stash`, per this session's own constraint against probing HEAD
  destructively), and the file was re-hashed:
  `8e9980c4fdfab6c5a48136bd61453b79e6830cdc80ca51a76b2f5bbfc1a166aa` — identical
  to the pre-mutation hash, confirming an exact, clean revert. `git status
  --short` after the revert showed no diff on this file.

## `data/exports/latest_articles.json` — confirmed untouched

This file was already dirty at session start (per `baseline.md`) and is
never written by any test path in this repository except
`CollectionRunWorkflow._run()`'s real (non-dry-run) export call, which no
unit/property/integration test in this session's runs exercises (every test
that touches an export file uses `tmp_path`, confirmed by grepping every
reference to `latest_articles.json` under `news_collector/`, `tests/`,
`scripts/`, and `apps/`). Its on-disk mtime (`2026-09-13 12:37:55`) predates
this session's start (first command timestamped `2026-09-13 23:5x`) by
roughly 11 hours, confirming directly — not just by code inspection — that
none of this session's `pytest`/`make` runs modified it further.

## Concurrent-work note

While this session ran, two other files unrelated to Plan 080 Phase 0/1
picked up uncommitted changes from what appears to be other concurrent
activity in the same checkout (not caused by any command in this session):
`docs/AGENTS.md`, `docs/INDEX.md`, `docs/ci.md`, `plans/081/tests/inventory.json`,
`plans/081/tests/results.md`, `plans/081/todo.md`. None of these were read,
edited, or relied upon by this phase's work. `news_collector/logic/workflows/pipeline_e2e.py`
remained dirty throughout (the pre-existing concurrent frontmatter-parsing
fix noted in `baseline.md`) and was never edited here — see the `make type`
result below for how its incompleteness surfaced in the full-suite run.

Operationally relevant beyond this plan: the set of concurrently-dirty files
grew over the course of this session (`docs/AGENTS.md` appeared after
`docs/INDEX.md`/`docs/ci.md`/`plans/081/tests/*`/`plans/081/todo.md` were
already dirty), meaning another agent/session was actively writing to this
same checkout throughout. Whoever picks up Plan 080 Phase 2 should re-check
`git status --short` fresh rather than trust this file's snapshot.

## Verification (exact commands, exit codes, pass/fail counts)

```
$ .venv/bin/python -m pytest tests/property/test_workflow_lifecycle_stateful.py tests/unit/logic/workflows/test_collection_run_workflow.py tests/unit/logic/workflows/test_publication_run_workflow.py --no-cov -q
.......................................................                  [100%]
55 passed in 7.48s
exit 0
```

```
$ .venv/bin/python -m pytest tests/test_serving_admin_api.py --no-cov -q
.................................................................        [100%]
65 passed in 8.38s
exit 0
```

```
$ make lint
```
First run failed: `black --check` flagged the new file's formatting
(`would reformat .../test_workflow_lifecycle_stateful.py`, 1 file, exit 1).
Fixed by running `.venv/bin/python -m black tests/property/test_workflow_lifecycle_stateful.py`
directly (this repo's own formatter, on a file this session authored — not a
production-code or scope violation). Re-ran `make lint`: `All done!
568 files would be left unchanged. All checks passed!` — exit 0. Re-ran the
pytest command above afterward to confirm the reformatted file still passes
(55 passed, unchanged).

```
$ make type
```
Overall exit: **nonzero** (`make: *** [Makefile:244: typecheck] Error 1`).
Breakdown (the `typecheck` Make target runs mypy, then a full
coverage-instrumented pytest run over all of `tests/` including
`tests/e2e_pipeline`, then the coverage ratchet check, each line aborting
the recipe on nonzero exit):
- **mypy**: passed. Make semantics guarantee this — the mypy command has no
  `-` prefix, so a nonzero mypy exit would have aborted the recipe before
  pytest ever ran; the full pytest coverage report and summary are present
  in the captured output, proving mypy returned 0.
- **pytest (full suite with coverage)**: **5 failed, 2372 passed, 5 skipped**
  in 639.36s. All 5 failures independently confirmed pre-existing and
  unrelated to this phase's changes (none of the failing files import or
  exercise `collection_run_workflow.py`, `publication_run_workflow.py`, or
  the new property test file):
  - 4x `tests/e2e_pipeline/test_pipeline_e2e.py`
    (`test_pipeline_e2e_scenarios[happy_path_latam_winner-True-None]`,
    `test_pipeline_e2e_scenarios[low_value_beats_high_value_regression-True-None]`,
    `test_happy_path_captures_generated_markdown_artifact`,
    `test_pipeline_e2e_bundle_root_is_repeatable`). Reproduced identically
    in full isolation: `.venv/bin/python -m pytest tests/e2e_pipeline/test_pipeline_e2e.py --no-cov -q -p no:randomly`
    → same 4 failed, 9 passed, 220.85s, with only that one file collected
    (the new property file not even present in the run). `git diff
    news_collector/logic/workflows/pipeline_e2e.py` shows this file mid-edit
    for a frontmatter block-style-list parsing fix — the pre-existing
    concurrent WIP this task's instructions explicitly named and asked not
    to be touched or assumed away.
  - 1x `tests/unit/test_enrichment_metrics_store.py::TestBufferedFlushEquivalence::test_interleaved_attempts_and_successes_match_between_immediate_and_batched`.
    Reproduced in isolation: `.venv/bin/python -m pytest tests/unit/test_enrichment_metrics_store.py::TestBufferedFlushEquivalence::test_interleaved_attempts_and_successes_match_between_immediate_and_batched --no-cov -q -p no:randomly`
    → 1 passed. Consistent with this exact file's documented history of
    order-dependent global-state-pollution flakiness under the suite's
    `-p randomly` ordering (see `todo-flaky-tests.md` at the repo root,
    BUG-2, already closed for a different symptom in that file).
- **coverage ratchet**: never reached by `make type` itself (the recipe
  aborted at the failing pytest line before this line could run). Run
  manually against the coverage.xml that pytest had already written:
  `COVERAGE_XML=reports/coverage/coverage.xml bash scripts/coverage_ratcheter.sh check`
  → `[coverage-ratchet] OK — total 87.74%, baseline 85.20%, changed files
  passed`, exit 0.
- `collection_run_workflow.py` coverage in this run: 98.73% statements.
  `publication_run_workflow.py`: 92.42% statements. No coverage regression.

**Conclusion for `make type`**: mypy and the coverage ratchet both pass;
the target's nonzero exit is caused entirely by pre-existing, independently
reproduced, unrelated failures (concurrent WIP + one documented flaky test),
not by anything introduced in Phase 0/1.

```
$ make test
2364 passed, 5 skipped, 1 warning in 82.44s (0:01:22)
exit 0
```
(`make test` excludes `tests/e2e_pipeline` per its own recipe
`--ignore=tests/e2e_pipeline`, so the concurrent-WIP failures do not surface
here. Clean pass.)

```
$ make test-boundaries
tests/unit/system/test_d1_pipeline_boundaries.py ...                     [100%]
3 passed in 0.43s
exit 0
```

## Summary

| Command | Result |
| --- | --- |
| new file + both existing unit test files | 55 passed, exit 0 |
| `tests/test_serving_admin_api.py` | 65 passed, exit 0 |
| `black` (own new file only, no production code) | 1 file reformatted, then re-verified clean |
| `make lint` | pass, exit 0 (after the `black` run above) |
| `make type` | **decomposed**: mypy pass -> pytest 5 failed / 2372 passed / 5 skipped (all 5 pre-existing/unrelated, each independently reproduced in isolation) -> coverage ratchet pass (run manually since the target never reached that line) -> target's own exit nonzero |
| `make test` | 2364 passed, 5 skipped, exit 0 |
| `make test-boundaries` | 3 passed, exit 0 |

W1-W5: all passed. No production defect found in
`CollectionRunWorkflow`/`PublicationRunWorkflow` by the machine. One cosmetic
observation (not a defect, not acted on): `start()`'s self-healing reap path
always writes `error_code="process_restarted"` / "Recovered at startup..." to
the recovered row even when the reap happens mid-service rather than at an
actual process restart — message wording only, no behavioral inconsistency.

No production code was left modified. `collection_run_workflow.py` was
temporarily mutated and exactly reverted (hash-verified) as part of the W5
sensitivity check above. `git status --short` after all of the above shows
this session's only footprint as two new files:
`plans/080/tests/baseline.md` and `tests/property/test_workflow_lifecycle_stateful.py`
(plus the two files explicitly named as out-of-scope at the start —
`data/exports/latest_articles.json` and
`news_collector/logic/workflows/pipeline_e2e.py` — both untouched by this
session, and the concurrent-work files noted above, also untouched).
