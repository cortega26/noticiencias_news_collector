# Plan 153: Stop the publish-batch dispatcher from touching a closed DB

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 82e7015e..HEAD -- news_collector/logic/workflows/publication_run_workflow.py news_collector/storage/database.py tests/conftest.py tests/unit/logic/workflows/ docs/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW-MED (thread coordination; production shutdown semantics must not change)
- **Depends on**: none
- **Category**: bug / tests (resolves GitHub issue #367)
- **Planned at**: commit `82e7015e`, 2026-10-19

## Why this matters

Issue **#367** records a `PytestUnhandledThreadExceptionWarning` from CI: a
`publish-batch-*` thread reached `publication_run_workflow.py:_run_batch` after
the test fixture had closed the `DatabaseManager`, and the `fail()` handler then
re-tried the same closed DB through `_merge_summary()`. pytest still reported
success, so the failure is invisible except as a warning — and in production a
shutdown that closes the DB while a batch is finishing has the same shape.

The root cause is still present: `_dispatch_batch` starts a **fire-and-forget
daemon thread** and keeps no reference to it, so nothing can wait for it, and the
autouse `_close_global_db_manager` fixture closes the manager immediately after
each test. Plan 149 fixed the *engine executor* lifecycle; this is a different
thread. It did not reproduce in one 113-test run of
`tests/test_serving_admin_api.py` (a race), which is exactly why the fix needs a
deterministic regression, not a re-run.

## Current state

- `news_collector/logic/workflows/publication_run_workflow.py:271-282`:

```python
    def _dispatch_batch(
        self,
        run_id: int,
        *,
        article_ids: list[int],
    ) -> None:
        threading.Thread(
            target=self._run_batch,
            args=(run_id, article_ids),
            daemon=True,
            name=f"publish-batch-{run_id}",
        ).start()
```

  The single-article path (`:264`) has the same shape. By contrast, the heartbeat
  thread is properly joined (`heartbeat_thread.join(timeout=5)` at `:353` and
  `:454`) — follow that precedent.
- `tests/conftest.py:45-51` — the autouse fixture that closes the global manager
  after every test:

```python
@pytest.fixture(autouse=True)
def _close_global_db_manager():
    yield
    manager = getattr(database_module, "_db_manager", None)
    if manager is not None:
        manager.close()
        database_module._db_manager = None
```

- `news_collector/logic/workflows/publication_run_workflow.py` — `complete()` /
  `fail()` open a session via `self._db.get_session()`; `fail()`'s fallback path
  re-enters the DB through `_merge_summary()` even when the first call already
  failed (the issue's second bullet).
- Existing behaviour tests: `tests/unit/logic/workflows/test_publication_run_workflow.py`
  and `test_publication_batch.py` (fixtures build a real SQLite manager via
  `DatabaseManager({"type": "sqlite", ...})`).

## Commands you will need

| Purpose          | Command                                                                | Provenance | Expected on success            |
|------------------|------------------------------------------------------------------------|------------|--------------------------------|
| Install/baseline | `make bootstrap`                                                       | declared   | exit 0                         |
| Lint             | `make lint`                                                            | declared   | exit 0                         |
| Types + coverage | `make type`                                                            | declared   | exit 0                         |
| Unit suite       | `make test`                                                            | declared   | all pass                       |
| Integration      | `make test-integration`                                                | declared   | all pass                       |
| Boundaries       | `make test-boundaries`                                                 | declared   | exit 0                         |
| Focused tests    | `.venv/bin/pytest tests/unit/logic/workflows -q --no-cov`               | declared   | all pass                       |
| Ledger           | `make plans-ledger-check`                                              | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared`.

## Scope

**In scope**:

- `news_collector/logic/workflows/publication_run_workflow.py` — thread registry +
  join helper; `fail()` must not re-enter a DB that just failed
- `tests/conftest.py` — join dispatched threads **before** closing the global
  manager (same manual style as the existing fixture; no `monkeypatch`)
- `tests/unit/logic/workflows/test_publication_run_workflow.py` or a new
  `test_publication_thread_lifecycle.py` in the same directory
- `docs/AGENTS.md`/`docs/PIPELINE_CONTRACTS.md` only if they describe the
  dispatch lifecycle (likely not; verify)

**Out of scope** (do NOT touch):

- `publication_pipeline.py` (the run body; plan 133/149 own it).
- Any change to how a batch is *run*, its ordering, or its per-item outcomes.
- The heartbeat logic (already joined).
- Making the batch dispatch synchronous (that would change production
  behaviour — out of scope by design).

## Git workflow

- Branch: `advisor/153-publish-batch-thread-lifecycle`
- Conventional commits, e.g.
  `fix(workflows): join dispatched publication threads before closing the DB (plan 153)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

`make bootstrap`, `make lint`, `make type`, `make test`,
`make test-integration`. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Make the race deterministic (red first)

1. Write a regression test that fails on the current code, **without sleeps**:
   - build a real SQLite `DatabaseManager` and a `PublicationRunWorkflow`;
   - replace/monkeypatch the batch body (`_run_batch`) with a function that waits
     on a `threading.Event` (the test sets it only after closing the manager),
     then calls the real `complete()`/`fail()` path;
   - dispatch the batch, close the manager, set the event, and wait for the
     thread;
   - assert that no exception escaped the thread (e.g. capture
     `threading.excepthook` into a list and assert it is empty, or assert the
     thread's outcome is recorded rather than raised).
   The issue's exact failure is an unhandled exception in
   `publish-batch-*` — capture it precisely, not via "no warning in output".

**Verify**: the new test fails against the unmodified source (record the failure).

### Step 2: Fix the lifecycle

2. Keep a reference to every dispatched thread (a small module- or
   instance-level registry guarded by a lock, pruned when the thread ends) and
   add `join_dispatched_threads(timeout: float | None = None) -> None` to the
   workflow. Follow the heartbeat's join style; do not block production callers
   (only the explicit helper waits).
3. In `tests/conftest.py`, call the workflow-side helper before closing the
   global manager. The fixture must not depend on `monkeypatch` and must keep the
   existing manual save/restore style. The registry must be discoverable from the
   fixture without importing a test-only path — expose it as a module function
   (e.g. `join_dispatched_publication_threads(timeout=...)`) in
   `publication_run_workflow.py`.
4. Fix the `fail()` fallback: if `complete()`/`fail()` cannot open a session
   (closed engine / `SQLAlchemyError`), log the original error **and** the
   persistence failure with context (run id, article id) and return — do not
   re-enter `_merge_summary()`, which retries the same dead handle and hides the
   original cause. This is defense-in-depth, not a replacement for the join.

**Verify**: the Step 1 test passes; `make test` green; focused
`.venv/bin/pytest tests/unit/logic/workflows -q --no-cov` green.

### Step 3: Keep production semantics identical

5. Confirm the dispatch still returns immediately (the API path must not block on
   a batch). Add/adjust one test asserting `start_batch` returns before the body
   finishes (Event-controlled, no sleeps).
6. Confirm the heartbeat join behaviour is untouched.

**Verify**: the new "returns immediately" test passes; `make test-boundaries`
green.

### Step 4: Prove the warning is gone

7. Run the full e2e-marked serving suite repeatedly, e.g.
   `for i in 1 2 3; do .venv/bin/pytest tests/test_serving_admin_api.py -q --no-cov; done`
   and the integration suite, checking the summary for
   `PytestUnhandledThreadExceptionWarning` (grep the output). Record the counts.

**Verify**: no warning in the repeated runs; all tests pass.

## Test plan

- New deterministic regression (Step 1) — the deliverable.
- New "dispatch does not block" test (Step 3).
- If the `fail()` fallback changes, a test asserting the original error is logged
  and the second DB access is not attempted (monkeypatch `get_session` to raise
  and assert a single call).

**Verify**: `make test && make test-integration && make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-integration`, `make test-boundaries` exit 0
- [ ] The Step 1 regression fails on the pre-change source (proof recorded) and passes after
- [ ] `grep -n "join_dispatched" news_collector/logic/workflows/publication_run_workflow.py tests/conftest.py` → wired in both
- [ ] `grep -c "Thread(" news_collector/logic/workflows/publication_run_workflow.py` shows every dispatch path keeps a reference (diff review)
- [ ] Repeated serving-suite runs emit no `PytestUnhandledThreadExceptionWarning` (counts recorded)
- [ ] No sleeps introduced (`grep -n "sleep(" tests/unit/logic/workflows/` unchanged)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 153 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- Production code that calls `start_batch` turns out to depend on the thread
  being unreachable (e.g. a test asserts on a thread list) → report before
  changing the registry shape.
- Joining in the conftest fixture would deadlock a test that intentionally closes
  the DB while a batch runs → report the test; do not add a timeout that hides it.
- The `fail()` fallback is load-bearing for a real recovery path → report with
  the callers before removing the retry.

## Maintenance notes

- The invariant to protect: **every daemon thread that can touch the DB is
  joinable**, and teardown joins before closing. If a future dispatch path is
  added, register it the same way.
- Reviewer should scrutinise: the registry's thread-safety and pruning (no
  unbounded growth in a long-lived serving process), and that `fail()` still
  records the original error rather than swallowing it.
- **Deferred:** making the batch run in a managed executor (shared pool) instead
  of per-run threads — larger design change, unblocked by a decision on the
  serving process's shutdown contract.
