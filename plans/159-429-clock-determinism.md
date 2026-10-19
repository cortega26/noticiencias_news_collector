# Plan 159: Make the 429 Retry-After test deterministic (no wall-clock window)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 8aa43fc8..HEAD -- tests/test_reliability_features.py news_collector/collectors/html_collector.py news_collector/collectors/base_collector.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (test-only)
- **Depends on**: none (152/153 removed the config and thread flakes; this is the last known one)
- **Category**: tests (flaky)
- **Planned at**: commit `8aa43fc8`, 2026-10-19

## Why this matters

The ledger has carried `tests/test_reliability_features.py::test_429_retry_after_handling`
as a watch item since plan 096: it **fails under the randomized full suite and
passes in isolation**. The cause is visible in the test itself — it asserts a
**wall-clock window**:

```python
    forced_time = call_args.kwargs["force_cooldown_until"]
    now = datetime.now(timezone.utc)
    diff = (forced_time - now).total_seconds()
    assert 50 < diff < 70  # Allow some execution time buffer
```

The collector computes `cooldown_until = its_now + 60 s`; the test then measures
against a **later** `now`. On a loaded or randomly-ordered run, more than 10
seconds can pass between those two instants, the difference drops below 50, and
the test fails — with no product bug involved. After plans 152 (config isolation)
and 153 (thread joins) this is the last recorded flake; removing it makes the
randomized suite trustworthy.

## Current state

- `tests/test_reliability_features.py:10-49` — the test. It mocks `httpx.AsyncClient`
  (429 + `Retry-After: 60`), patches `_respect_robots`, runs
  `collect_from_source_async`, asserts `success is False`, `articles_found == 0`,
  one `update_source_circuit_state` call with a non-None `force_cooldown_until`,
  then the 50–70 s window at `:48-49`.
- The production path that computes the cooldown: read
  `news_collector/collectors/html_collector.py` and
  `news_collector/collectors/base_collector.py` — find where the 429 handler
  computes `force_cooldown_until` (the `Retry-After` parse and the
  `datetime.now(timezone.utc)` call). Record the exact `file:line` and whether
  the clock read is a module-level `datetime` (patchable) or a helper.
- Precedent for clock injection in this repo: plan 127 replaced wall-clock sleeps
  with thread-join/fake-clock handshakes; `tests/conftest.py` freezes
  `_FIXED_PAYLOAD_INSTANT` for payload timestamps.

## Commands you will need

| Purpose          | Command                                                              | Provenance | Expected on success          |
|------------------|----------------------------------------------------------------------|------------|------------------------------|
| Install/baseline | `make bootstrap`                                                     | declared   | exit 0                       |
| Lint             | `make lint`                                                          | declared   | exit 0                       |
| Types + coverage | `make type`                                                          | declared   | exit 0                       |
| Unit suite       | `make test`                                                          | declared   | all pass                     |
| Focused test     | `.venv/bin/pytest tests/test_reliability_features.py -q --no-cov`     | declared   | all pass                     |
| Repeated 20x     | `for i in $(seq 1 20); do .venv/bin/pytest tests/test_reliability_features.py::test_429_retry_after_handling -q --no-cov -p no:randomly \|\| break; done` | declared | 20 passes |
| Ledger           | `make plans-ledger-check`                                            | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared`.

## Scope

**In scope**:

- `tests/test_reliability_features.py` — the 429 test (and only that test)
- A tiny fake-clock helper if needed (local to the test module; do not add a
  conftest-wide fixture)

**Out of scope** (do NOT touch):

- The collector's behaviour (the cooldown semantics are correct: it honours
  `Retry-After`). If you believe production code is wrong, STOP and report.
- Other tests in the file (fix only the 429 one; note any sibling with the same
  wall-clock pattern in your report).
- Any other file.

## Git workflow

- Branch: `advisor/159-429-clock-determinism`
- Conventional commit, e.g.
  `test(reliability): freeze the clock in the 429 Retry-After test (plan 159)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline and find the clock seam

`make bootstrap`, `make lint`, `make test`, the focused test, and the 20× loop.
Record the production `file:line` that reads the clock for the cooldown.

**Verify**: gates green; the clock read is named in your report.

### Step 1: Freeze the clock

1. Patch the **narrowest** seam that makes the collector see a fixed instant
   (e.g. `patch("news_collector.collectors.html_collector.datetime")` with a
   frozen `now`, or its module-level `now()` helper if one exists). Keep the
   patch scoped to this test.
2. Replace the window assertion with the **exact** expectation:
   `forced == frozen_now + timedelta(seconds=60)` (or the value the production
   path derives from `Retry-After`). Keep the existing behavioural assertions
   (`success is False`, `articles_found == 0`, one DB call) unchanged.
3. No sleeps, no tolerance windows. If the production path rounds or clamps,
   assert the documented result (read it first).

**Verify**: the focused test passes; the assertion no longer reads the wall clock.

### Step 2: Prove determinism

4. Parametrise the frozen instant over at least two distinct dates (e.g. a normal
   date and one near a year boundary) and assert the same exact delta both
   times — that pins "no wall-clock dependence".
5. Run the 20× loop again.

**Verify**: 20/20 passes; the parametrised cases pass.

### Step 3: Return the flake to the ledger (report only)

6. Put the commands/results in your report; the reviewer will mark the ledger's
   flaky-test watch item resolved.

**Verify**: `make test` green.

## Test plan

- The rewritten test (exact clock, parametrised instant) is the deliverable.
- If a sibling test in the same file has the same wall-clock window, list it in
  NOTES (do not fix it here).

**Verify**: `make test && make type && make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] The test no longer calls `datetime.now()` for its assertion (grep the test body)
- [ ] The 20× loop passes; two frozen instants both pass with the exact delta
- [ ] The behavioural assertions (success/found/DB call) are unchanged
- [ ] `git diff --name-only main...HEAD` lists only `tests/test_reliability_features.py`
- [ ] `plans/README.md` row 159 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- The cooldown is computed from a **monotonic** clock or from a value captured in
  another module, so freezing requires patching more than ~3 symbols → report the
  seams; do not add a global clock abstraction for one test.
- The exact delta does not match the documented production rounding → report the
  observed value and the production code that produces it.
- The test fails 20/20 windows today (i.e. it is not a flake but a real
  determinism bug) → report; do not "fix" it by widening the window.

## Maintenance notes

- The rule: **assert derived time values against the same frozen clock that
  produced them**, never against a later `now`.
- Reviewer should scrutinise: the patch target is the module the collector
  actually reads, and the test still fails if `Retry-After` is ignored.
- **Deferred:** auditing the whole suite for other wall-clock windows. Unblocked
  by a decision to run a timed suite sweep (`make test-timeshift` already covers
  date-dependent tests).
