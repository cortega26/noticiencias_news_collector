# Plan 152: Make the unit suite order-independent — stop the runtime-config snapshot leak

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1661326e..HEAD -- news_collector/config/settings.py tests/conftest.py tests/unit/collectors/test_admission.py tests/security/test_ssrf_protection.py docs/testing.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (the fix is test-harness scoped; a production-code fix is
  only allowed if the root cause is there)
- **Depends on**: none
- **Category**: tests (verification baseline)
- **Planned at**: commit `1661326e`, 2026-10-19

## Why this matters

Three independent runs have now produced the same class of failure, and it costs
real time on every plan: a randomized order leaves a **global runtime-config
snapshot** behind, and later tests read it as if it were their own.

- Recorded in the ledger (2026-10-12): seed `303127521` produced **13 setup
  errors** — `KeyError: 'type'` in `DatabaseManager._setup_database` via
  `get_runtime_config().database_config` — "a residual of the plan-126 class
  where `refresh_runtime_config()` can publish a snapshot built from an empty
  `RUNTIME`".
- Reproduced during plan 133 (2026-10-19): seed `722672841` failed **7 tests**
  (6 in `tests/unit/collectors/test_admission.py`, 1 in
  `tests/security/test_ssrf_protection.py`) with `min_content_length` falling
  back to `1000` and a foreign DB config; the executor proved it reproduces
  identically on an **unmodified snapshot** of the parent commit.
- Separately, `tests/test_reliability_features.py::test_429_retry_after_handling`
  is recorded as an order/load-dependent flake.

For an executor this is indistinguishable from a real regression: the gates go
red on a clean tree, and a correct STOP costs a whole round trip. This is the
verification baseline every other plan depends on — that is why it is P1.

## Current state

- `news_collector/config/settings.py` — the global state that leaks:
  - `:57` `RUNTIME = RuntimeSettings()` (mutated in place by the resolvers at
    `:208-237`: paths, environment, builders).
  - module globals `_CONFIG_STATE`, `_CONFIG_VERSION`, `_CURRENT_SNAPSHOT`
    (declared in `refresh_runtime_config`'s `global` statement at `:360`).
  - `:351-381` `refresh_runtime_config(config: Any | None = None)`:
    `cfg = config or load_config()` → validate → `_resolve_paths` →
    `_resolve_environment` → `_resolve_builders` → atomically swaps the snapshot.
    Its docstring promises rollback safety for *failed validation*, not
    isolation between callers.
- `tests/conftest.py` — already has the right pattern and a warning worth
  respecting (documented on the first fixture): two autouse fixtures
  (`_allow_example_com_source_images`, `_close_global_db_manager`), and an
  explicit note that an autouse fixture must **not** depend on `monkeypatch`
  because that changes the teardown order for every test that patches module
  state itself.
- **19 test files** call `refresh_runtime_config()` (e.g.
  `tests/unit/collectors/test_rss_collector.py:132,232,538`), and several tests
  construct partial/`SimpleNamespace` configs; `refresh_runtime_config` already
  guards `_CONFIG_STATE` against non-`Config` doubles (see its comment about
  pytest-randomly), but `RUNTIME` is mutated *before* that guard.
- `Makefile`'s `test`/`typecheck` targets run pytest with `-p randomly`, so the
  order varies per run; the seeds above reproduce specific orders.

## Commands you will need

| Purpose                | Command                                                                 | Provenance | Expected on success            |
|------------------------|-------------------------------------------------------------------------|------------|--------------------------------|
| Install/baseline       | `make bootstrap`                                                        | declared   | exit 0                         |
| Lint                   | `make lint`                                                             | declared   | exit 0                         |
| Types + coverage       | `make type`                                                             | declared   | exit 0                         |
| Unit suite             | `make test`                                                             | declared   | all pass                       |
| Reproduce seed A       | `.venv/bin/pytest tests -q --no-cov -p randomly --randomly-seed=722672841` | declared | **fails today** (7 tests)      |
| Reproduce seed B       | `.venv/bin/pytest tests -q --no-cov -p randomly --randomly-seed=303127521` | declared | **fails today** (setup errors) |
| Stable-order run       | `.venv/bin/pytest tests -q --no-cov -p no:randomly`                     | declared   | all pass (baseline)            |
| Ledger                 | `make plans-ledger-check`                                               | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared` (read from the `Makefile`/CI; the advisor reproduced
neither seed in this session — the executor must).

## Scope

**In scope**:

- `tests/conftest.py` — one new autouse fixture that snapshots and restores the
  runtime-config globals around every test
- The specific test file(s) that leak the state, if the fixture-based fix is not
  enough (fixture-level changes only: save/restore or explicit refresh; **no
  assertion changes**)
- `news_collector/config/settings.py` — **only if Step 2 proves the leak is in
  production code** (e.g. `RUNTIME` is mutated before validation, so a rejected
  config still leaks path/environment fields); a fix there must preserve
  documented behaviour and add a test
- `docs/testing.md` — one short paragraph on the guard and how to reproduce the
  seeds

**Out of scope** (do NOT touch):

- Any test's assertions, expected values, or names; any test deletion.
- The pytest configuration in `pyproject.toml` (no marker/seed changes).
- `tests/test_reliability_features.py`'s 429 test — the load flake is separate;
  do **not** quarantine or rewrite it here.
- Production behaviour beyond the `settings.py` rollback-safety fix described
  above.

## Git workflow

- Branch: `advisor/152-runtime-config-isolation`
- Conventional commits, e.g.
  `test(config): restore the runtime-config snapshot around every test (plan 152)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline and reproduce both seeds

Run `make bootstrap`, `make lint`, `make test`, then the two seed commands in the
table. Record the exact failing tests/errors for each seed (this is the proof the
plan is about).

**Verify**: `make test` green; seed `722672841` fails with the recorded 7 tests;
seed `303127521` fails with the recorded setup errors. If a seed does **not**
fail, record that (the flake may have been fixed in passing) and continue with
the other; if both pass, STOP and report — the plan's premise is gone.

### Step 1: Localize the leak

1. Add a **temporary** autouse fixture in `tests/conftest.py` (or a throwaway
   conftest in a scratch copy) that records, before each test, the identity of
   `settings._CURRENT_SNAPSHOT` / `_CONFIG_STATE` / `_CONFIG_VERSION` and the
   values of `settings.RUNTIME.database_config`/`min_content_length`, compares
   them after the test, and prints the test id when they changed.
2. Run the failing seed with `-x` and this instrumentation, and identify **the
   test that changes the state** (not the test that fails later). Record it.

**Verify**: the recorded leaker test id and the specific field(s) that changed.

### Step 2: Fix it at the right layer

3. **Preferred (test-harness) fix**: add a permanent autouse fixture in
   `tests/conftest.py` that snapshots the runtime state before each test and
   restores it afterwards, following the file's existing manual save/restore
   style (do **not** use `monkeypatch` — see the fixture docstring's warning):
   - snapshot: the snapshot object identity + `_CONFIG_STATE`/`_CONFIG_VERSION`
     + the mutating `RUNTIME` fields the resolvers write (at minimum
     `database_config`, `min_content_length`, `data_dir`, `environment`);
   - restore in `finally`, tolerating attributes that did not exist.
   Keep it cheap (no deep copies of the whole config if identity restoration
   suffices — measure before/after on one seed).
4. **Production fix (only if Step 1 proves it)**: `refresh_runtime_config`
   mutates `RUNTIME` before validation. If the leaker is a *rejected* refresh,
   reorder so validation precedes mutation, or snapshot/rollback `RUNTIME` on
   failure. Preserve the documented "rollback-safe" promise and add a test
   (a rejected `refresh_runtime_config` leaves `RUNTIME` unchanged).
5. If the leaker is a test that deliberately configures a different runtime for
   its own scope, make it refresh once in setup and restore in teardown (the
   fixture in step 3 will do that automatically once it is in place).

**Verify**: both seed commands now pass; `-p no:randomly` still passes;
`.venv/bin/pytest tests/unit/collectors/test_admission.py tests/security/test_ssrf_protection.py -q --no-cov` passes in isolation.

### Step 3: Prove the guard, not just the seeds

6. Run at least five additional seeds (e.g. `--randomly-seed=1,2,3,42,999`) and
   the default `make test` several times. Record the commands and results.
7. Prove the guard is load-bearing: temporarily disable the new fixture (comment
   it out), confirm a seed fails again, then restore it.

**Verify**: all seeds green with the fixture; the disabled-fixture run reproduces
the failure.

### Step 4: Document and keep the ledger honest

8. Add one short paragraph to `docs/testing.md`: the guard exists, why (the two
   recorded seeds), and how to reproduce (`-p randomly --randomly-seed=N`).
9. Update the ledger's flaky-test watch item in `plans/README.md`? **No** — your
   reviewer maintains the index; put the evidence in your report.

**Verify**: `make docs-check` exits 0.

## Test plan

- The permanent guard fixture is the deliverable; the verification is the seed
  matrix above plus `make test` / `make type`.
- If a production fix lands (step 4), add a direct unit test for the rollback
  property, modelled on the existing `refresh_runtime_config` tests
  (`grep -rn "refresh_runtime_config" tests/` for the pattern).

**Verify**: `make test`, `make type`, `make lint`, `make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] Seed `722672841` and seed `303127521` both pass (with the exact commands recorded)
- [ ] At least five additional seeds pass; the disabled-fixture run reproduces a failure
- [ ] The guard fixture is autouse, documented, and does not depend on `monkeypatch`
- [ ] No test assertion/name changed (diff shows fixture/harness changes only)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 152 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- Both recorded seeds pass on the unmodified tree → the premise is gone; report
  and stop.
- Restoring the runtime state makes a test fail because it **legitimately**
  depends on config written by an earlier test → report that test and its
  dependency; do not paper over it with ordering.
- The root cause is production code and the minimal fix would change documented
  semantics beyond rollback safety → report before changing it.
- The fixture proves unreliable (e.g. it cannot restore the state because a test
  replaced the module object) → report the mechanism instead of adding more
  bookkeeping.

## Maintenance notes

- The guard makes the suite hermetic by construction: any future test that calls
  `refresh_runtime_config()` is covered without remembering to clean up. If a
  test needs state to survive between tests (it should not), that is a design
  smell to review — not a reason to weaken the fixture.
- Reviewer should scrutinise: the fixture's snapshot/restore field list is
  complete for the resolvers (`_resolve_paths`/`_resolve_environment`/
  `_resolve_builders`), and the production fix (if any) keeps the "failed
  validation leaves RUNTIME untouched" promise.
- **Deferred:** quarantining or fixing the separate
  `test_429_retry_after_handling` load/timing flake — it is a different class
  (real sleeps/timers), unblocked by nothing in this plan.
