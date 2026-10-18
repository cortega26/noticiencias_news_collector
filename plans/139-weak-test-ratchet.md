# Plan 139: Wire the weak-test detector into CI with a ratchet

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- scripts/test_suite_audit.py Makefile .github/workflows/ tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none, but **sequence against plans 137, 138, 143, 144, 145** —
  shared `Makefile`/CI files
- **Category**: tests
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`docs/AGENTS.md` §4.1 rejects tests that assert nothing, assert on fakes, or
execute no measured line — and the repo already has a detector for exactly that
(`scripts/test_suite_audit.py`, driven by `make test-audit`). It is wired to
nothing: it is absent from `make verify-ci` (`Makefile:249`) and from every
workflow. A static AST scan of `tests/` finds dozens of test functions with no
assertion and no `raise` in their own body (a preliminary scan found 47; the
repo's own detector is the authority — see Step 1). Without an enforcement hook,
the backlog can only grow, and every future "green CI" claim overstates how much
the suite actually verifies.

## Current state

- `Makefile:415-419`:

```make
test-audit: bootstrap ## Audit the test suite: coverage incl. noticiencias+scripts, weak tests, tests touching no code (slow: full run)
	@mkdir -p reports/audit
	@$(PYTHON_BIN) -m pytest tests --ignore=tests/e2e_pipeline --collect-only -q --no-cov -p no:randomly 2>/dev/null | grep "::" > reports/audit/collected.txt
	@$(PYTHON_BIN) -m pytest tests --ignore=tests/e2e_pipeline -q -p no:randomly --cov=news_collector --cov=apps --cov=noticiencias --cov=scripts --cov-config=scripts/audit.coveragerc --cov-context=test --cov-report=json:reports/audit/cov.json --cov-report=
	@$(PYTHON_BIN) scripts/test_suite_audit.py --coverage reports/audit/cov.json --collected reports/audit/collected.txt
```

- `scripts/test_suite_audit.py`
  - `main()` (`:318-324`) — `--coverage` is **required**; other flags:
    `--collected`, `--tests`, `--out`, `--threshold`.
  - `analyze_test_quality()` (`:216-237`) — static scan; appends
    `f"{path}::{fn.name}"` to `quality.no_assertion` when `_has_assertion(fn)`
    (`:201`) is false. Mock-heavy detection lives in the same function.
  - `render_markdown()` and the JSON output (`:340-360`) already expose
    `no_assertion` and `mock_heavy`.
  - `tests_touching_no_code()` needs the coverage JSON — that part is the slow one.
- Precedent for a checked-in baseline + gate: `audit-todos-baseline` /
  `audit-todos-check` (`Makefile:470`, `tools/scan_placeholders.py`) and
  `inventory-check`/`inventory-refresh`.

## Commands you will need

| Purpose            | Command                                                            | Provenance | Expected on success            |
|--------------------|--------------------------------------------------------------------|------------|--------------------------------|
| Install/baseline   | `make bootstrap`                                                   | declared   | exit 0                         |
| Lint               | `make lint`                                                        | declared   | exit 0                         |
| Types + coverage   | `make type`                                                        | declared   | exit 0                         |
| Unit suite         | `make test`                                                        | declared   | all pass                       |
| Static audit (new) | `make weak-tests-check`                                            | declared   | exit 0, prints the counts      |
| Ledger             | `make plans-ledger-check`                                          | declared   | `validate_plans_ledger: OK`    |

Provenance: all `declared`.

## Scope

**In scope**:

- `scripts/test_suite_audit.py` — add a static-only mode (no coverage needed)
- `Makefile` — `weak-tests-check` (and a refresh target if you use a baseline file)
- `audit/` — the new baseline JSON (checked in)
- `.github/workflows/ci.yml` **or** a small weekly workflow — the enforcement hook
- `docs/ci.md` — describe the gate
- `tests/` — fixes for the specific assertion-free test functions you can repair
  safely (see Step 3)

**Out of scope** (do NOT touch):

- Test selection, markers, or `pyproject.toml`'s pytest config.
- The `mock_heavy` list (record it, do not gate on it yet).
- Rewriting tests whose only issue is that they assert through a helper.

## Git workflow

- Branch: `advisor/139-weak-test-ratchet`
- Conventional commit, e.g. `test(audit): gate assertion-free tests with a baseline ratchet (plan 139)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`. Red baseline → STOP
and report.

**Verify**: every command matches its expected result.

### Step 1: Get the authoritative count

1. Run the existing detector once, in its normal (slow) form, to get the
   authoritative `no_assertion` list: `make test-audit` then
   `.venv/bin/python -c "import json;d=json.load(open('reports/audit/test_audit.json'));print(len(d['no_assertion']));print('\n'.join(d['no_assertion'][:20]))"`.
   Record the count and the top entries. (`make test-audit` is slow — it runs the
   full suite; that is fine, once.)

**Verify**: the count and a written sample are recorded in the ledger row.

### Step 2: Add a static-only mode and a baseline gate

2. In `scripts/test_suite_audit.py`, make `--coverage` optional and add
   `--static-only`:
   - with `--static-only`, run only the AST analyses (`analyze_test_quality`)
     and write a reduced JSON (e.g. `no_assertion`, `mock_heavy`, `total_tests`)
     plus the markdown weak-test section;
   - the coverage-dependent sections (`critical_gaps`, `tests_touching_no_code`)
     must be skipped cleanly, and the script must exit 0;
   - keep the existing default behaviour byte-identical when `--coverage` **is**
     provided (prove it: run both and diff the outputs).
3. Add a **baseline** at `audit/weak_tests_baseline.json`
   (`{"no_assertion": [...sorted list...]}`), generated from Step 1.
4. Add `Makefile` targets:
   - `weak-tests-baseline`: refresh the baseline file (with a doc comment that
     refreshing is an explicit decision);
   - `weak-tests-check`: run the static mode, compare against the baseline and
     **fail when the list grows** (new entries), while allowing entries to shrink.
     Print the delta. Fail closed on a missing baseline (same style as
     `inventory-check`).
5. Wire `weak-tests-check` into `make verify-ci` (`Makefile:249`) — it is a
   seconds-long static scan; and add the Make target list update in `docs/ci.md`.

**Verify**: `make weak-tests-check` exits 0 on the unmodified tree; then append a
dummy assertion-free test to a scratch copy under `tests/` → the check exits 1
naming it; delete the scratch file.

### Step 3: Shrink the list where it is cheap and safe

6. Fix at most ~10 of the flagged entries that are plainly wrong and safe to
   repair — assert the observable outcome instead of nothing, or rename the test
   to say it is a smoke test (`test_..._smoke`) and add a comment explaining why
   an assertion is impossible. Do **not** delete tests as a shortcut.
   Examples seen in the preliminary scan (verify in your own list first):
   `tests/test_async_scoring.py:26` (print-only driver script),
   `tests/test_utils_security.py:11` ("Should not raise" — assert explicitly that
   no exception is raised and that a valid URL is accepted).
7. Re-run `make weak-tests-baseline` **only** after the repairs, so the baseline
   reflects the new lower count, and record both counts (before/after) in the
   ledger row.

**Verify**: `make weak-tests-check` exits 0; `make test` → all pass (your repairs
did not break anything).

### Step 4: Prove the gate runs in CI

8. If you wired it into `verify-ci`, no workflow change is needed (CI runs
   `make verify-ci`); say so. Otherwise add a weekly workflow that runs
   `make weak-tests-check` and nothing else.

**Verify**: the YAML parses; `grep -n "weak-tests-check" Makefile .github/workflows/*.yml docs/ci.md` shows the wiring.

## Test plan

- The gate itself is the test. Keep the static mode fast (< 30 s) — it must not
  run pytest.
- If you add tests for the new CLI flag, put them next to the existing
  `tests/test_scan_placeholders.py`-style tooling tests (or note that no unit
  test exists for the flag and why).

**Verify**: `make weak-tests-check && make test && make lint && make type` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `make weak-tests-check` exits 0 and fails when a new assertion-free test is added (both proven)
- [ ] Baseline file checked in at `audit/weak_tests_baseline.json`; count recorded before/after
- [ ] `make verify-ci` includes the check (or the weekly workflow exists) + `docs/ci.md` updated
- [ ] `make inventory-refresh` run if new top-level files/Make targets were added; `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (+ inventory baseline)
- [ ] `plans/README.md` row 139 updated; `make plans-ledger-check` → OK

## STOP conditions

- `make test-audit` cannot complete in the executor's environment (it runs the
  full suite) → report and stop rather than guessing the baseline count.
- The static scan's existing output is not deterministic (ordering) → sort before
  comparing, and if the entries themselves vary between runs, STOP and report
  (a nondeterministic gate must not be wired).
- More than ~10 flagged entries turn out to be legitimate smoke tests **and**
  removing them from the baseline would mask a real risk → keep them in the
  baseline and say so; do not delete tests.

## Maintenance notes

- `mock_heavy` is recorded but not gated on purpose; gating it is a follow-up
  decision (the audit's "assert on the fakes" rule needs a human in the loop).
- Reviewer should scrutinise: that the baseline can only shrink without an
  explicit reviewer-visible refresh, and that the static mode writes nothing
  outside `reports/audit/` and `audit/weak_tests_baseline.json`.
- **Deferred:** gating `mock_heavy` and `tests_touching_no_code`. Unblocked by
  the full-profile coverage work (plan 137) making "no measured line" meaningful
  for the e2e-marked suites too.
