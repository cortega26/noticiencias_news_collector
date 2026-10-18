# Plan 137: The coverage ratchet must measure the suites that cover the serving API

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- Makefile .coverage-baseline scripts/coverage_ratcheter.sh .github/workflows/ci.yml docs/ci.md pyproject.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED (a new recorded profile temporarily becomes the floor for
  changed files; the ratchet's grandfather rule prevents a 90 % cliff)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Every behavioural test of the admin/public API is marked `pytest.mark.e2e`
(`tests/test_serving_admin_api.py:25`, `tests/test_serving_api.py:14`,
`tests/test_webhook.py:16`), and the coverage ratchet only ever sees the **unit**
profile (`Makefile:262-263` runs the unit selection and passes
`COVERAGE_PROFILE=unit`). Consequence: the repo's largest module,
`news_collector/serving/api.py` (2 640 lines), is recorded in the committed
baseline at **24.77 % line / 3.73 % branch**, and the changed-file floor for it is
grandfathered to that value (`scripts/coverage_ratcheter.sh`, floor rule at the
`changed` loop). Deleting or gutting the 3 333-line admin API suite changes no
gate output whatsoever, and new untested serving code is measured against a
near-empty baseline. Fixing this is also the stated precondition for ever
splitting `api.py` (a split was deferred "until 127-style coverage exists" — the
behavioural suite exists; the *measurement* does not).

## Current state

- `Makefile:255-263` (`typecheck`, reached by `make type`):

```make
	@$(PYTEST) tests --ignore=tests/integration --ignore=tests/e2e_pipeline --ignore=tests/perf -m "not e2e and not perf" --cov-report=xml:$(COVERAGE_DIR)/coverage.xml --cov-report=html:$(COVERAGE_DIR)/html
	@COVERAGE_PROFILE=unit COVERAGE_XML=$(COVERAGE_DIR)/coverage.xml bash scripts/coverage_ratcheter.sh check
```

- `.github/workflows/ci.yml:210-240` — the `coverage` job downloads the unit
  artifact (`coverage-reports-unit`) produced by the `type` job and checks with
  `COVERAGE_PROFILE: unit`, `timeout-minutes: 5`, full fetch depth.
- `Makefile:276-277` — `test-integration` runs both legs with `--no-cov`.
- `scripts/coverage_ratcheter.sh`:
  - `record` writes `profiles[COVERAGE_PROFILE or "full"]` with
    `recorded_at`/`total_line`/`total_branch`/`files` (verified at
    `:205-216`).
  - `check` uses `profiles.full` when `COVERAGE_PROFILE=full`, otherwise the
    named profile, and **exits 1 if the named profile is missing** (`:252-261`).
  - Floors: `minimum_global = 72.0`, `minimum_changed = 90.0`,
    `minimum_branch = 70.0`; a changed file whose recorded baseline value is
    below the threshold keeps that lower value as its floor (grandfather rule).
- `.coverage-baseline` today has only `profiles.unit` (plus top-level
  `total_line`/`total_branch`, no `files`), with `serving/api.py` at
  `{"line": 24.77, "branch": 3.73}`.

## Commands you will need

| Purpose                | Command                                                                 | Provenance | Expected on success                |
|------------------------|-------------------------------------------------------------------------|------------|------------------------------------|
| Install/baseline       | `make bootstrap`                                                        | declared   | exit 0                             |
| Lint                   | `make lint`                                                             | declared   | exit 0                             |
| Types + coverage       | `make type`                                                             | declared   | exit 0 (unit profile unchanged)    |
| Unit suite             | `make test`                                                             | declared   | all pass                           |
| Integration            | `make test-integration`                                                 | declared   | all pass                           |
| Record full profile    | `COVERAGE_PROFILE=full COVERAGE_XML=reports/coverage/coverage-full.xml bash scripts/coverage_ratcheter.sh record` | declared | `baseline recorded` |
| Check full profile     | `COVERAGE_PROFILE=full COVERAGE_XML=reports/coverage/coverage-full.xml bash scripts/coverage_ratcheter.sh check` | declared | exit 0 |
| Baseline inspection    | `.venv/bin/python -c "import json;d=json.load(open('.coverage-baseline'));print(list(d['profiles']));print(d['profiles']['full']['files']['news_collector/serving/api.py'])"` | executed (advisor read the same structure) | `['unit', 'full']` and a line % well above 24.77 |
| Ledger                 | `make plans-ledger-check`                                               | declared   | `validate_plans_ledger: OK`        |

Provenance: the advisor verified the **structure** of `.coverage-baseline` and
the script's profile logic by reading them; it did not run any suite. All suite
commands are `declared`.

## Scope

**In scope**:

- `Makefile` — one new target that produces an instrumented union run (name it
  `coverage-full`)
- `.coverage-baseline` — add `profiles.full` (do **not** modify `profiles.unit`)
- `.github/workflows/ci.yml` — a job that produces the full-profile artifact and
  a check step (extend `integration` + `coverage`, or add one job — see Step 3)
- `docs/ci.md` — the job list must match reality after the change
- `scripts/coverage_ratcheter.sh` — only if a real defect blocks you (prefer not)

**Out of scope** (do NOT touch):

- `pyproject.toml`'s coverage settings and `omit` list.
- `make type`'s local behaviour (it stays the fast unit-profile gate).
- The `serving/api.py` split itself — that is a separate, later decision; this
  plan only makes it measurable.
- `make verify-ci` composition (plan 138 owns Makefile gate edits — sequence after).

## Git workflow

- Branch: `advisor/137-coverage-profile-full`
- Conventional commit, e.g. `test(coverage): ratchet the e2e-covered surface (plan 137)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then `make lint`, `make type`, `make test`,
`make test-integration` on the unmodified checkout. Red baseline → STOP.

**Verify**: every command matches its expected result.

### Step 1: Add the instrumented union target

1. Add to `Makefile` next to `typecheck`:

```make
coverage-full: bootstrap ## Run the union suite (unit + integration + e2e-marked) with coverage into coverage-full.xml
	@mkdir -p $(COVERAGE_DIR)
	@$(PYTEST) tests --ignore=tests/e2e_pipeline --ignore=tests/perf -m "not perf" -p no:randomly --cov-report=xml:$(COVERAGE_DIR)/coverage-full.xml --cov-report=
```

   Notes: keep `$(COVERAGE_DIR)` as used by the neighbouring targets; exclude
   `tests/e2e_pipeline` (it spawns git/npm and is covered by its own job) and
   `tests/perf`; `-p no:randomly` makes the *measurement* deterministic (say so
   in the target's comment). Verify the tab indentation — `make lint` checks it.
   **Adding a Make target requires `make inventory-refresh`** (see Done criteria).

**Verify**: `make coverage-full` exits 0 and `reports/coverage/coverage-full.xml` exists; `.venv/bin/python -c "import xml.etree.ElementTree as ET; print(ET.parse('reports/coverage/coverage-full.xml').getroot().get('line-rate'))"` prints a value **higher** than the unit run's.

### Step 2: Confirm the serving surface is now measured

2. Check the union report for `news_collector/serving/api.py` line coverage:
   `.venv/bin/python - <<'PY'` … parse the XML class for that filename and print
   line %. Expect materially more than 24.77 % (if it is not above ~40 %, STOP:
   something is deselecting the admin suites).

**Verify**: the printed number and the exact command in the ledger row.

### Step 3: Record the profile and wire CI

3. Record: `COVERAGE_PROFILE=full COVERAGE_XML=reports/coverage/coverage-full.xml bash scripts/coverage_ratcheter.sh record`
4. Verify the baseline diff touches **only** `profiles.full`
   (`git diff .coverage-baseline | head -40`; `profiles.unit` must be byte-identical).
5. Wire CI with the fewest added minutes. Preferred shape: extend the existing
   `integration` job (`.github/workflows/ci.yml:184-209`) to additionally run
   `make coverage-full` (or make `integration` instrument one of its legs),
   upload `reports/coverage/coverage-full.xml` as `coverage-reports-full`, then
   extend the existing `coverage` job (`:210-240`) with a second check step:

```yaml
        env:
          COVERAGE_XML: reports/coverage/coverage-full.xml
          BASE_REF: origin/${{ github.event.pull_request.base.ref }}
          COVERAGE_PROFILE: full
        run: |
          REF="${BASE_REF:-origin/main}"
          bash scripts/coverage_ratcheter.sh check --base-ref "$REF"
```

   Bump that job's `timeout-minutes` if needed. If you instead add a new job, keep
   it `needs: integration` (not `type`) and document the choice.

**Verify**: `COVERAGE_PROFILE=full COVERAGE_XML=reports/coverage/coverage-full.xml bash scripts/coverage_ratcheter.sh check` exits 0 on the unmodified tree; the YAML parses (`python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`).

### Step 4: Keep the docs true

6. Update `docs/ci.md`: the `coverage` job description (`:34`) and the job list
   (`:25-38`) to name both profiles and which artifact feeds which. Add one
   sentence stating that the full profile is the one that measures the
   e2e-marked suites, and why the unit profile remains for local speed.

**Verify**: `make docs-check` exits 0; `grep -n "coverage-full\|full profile\|COVERAGE_PROFILE" docs/ci.md` shows the new text.

## Test plan

- No new unit tests: the deliverable is the measurement. The verification is
  the recorded numbers plus the check command exiting 0.
- Regression guard: assert in the ledger row that `profiles.unit` is unchanged
  and that `serving/api.py`'s full-profile value is recorded (with the number).

**Verify**: `make test && make test-integration` → green; `make type` → green and
its check still uses the unit profile.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-integration` exit 0
- [ ] `make coverage-full` exits 0; `profiles.full` exists in `.coverage-baseline`
- [ ] `news_collector/serving/api.py`'s full-profile line coverage is recorded and
      is materially above 24.77 %
- [ ] `git diff .coverage-baseline` shows `profiles.unit` untouched
- [ ] CI YAML valid; the new check step present; `docs/ci.md` updated
- [ ] `make inventory-refresh` run (new Make target) and `make inventory-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files (plus the
      regenerated `audit/00_inventory.json`)
- [ ] `plans/README.md` row 137 updated; `make plans-ledger-check` → OK

## STOP conditions

- The union run is not green on the unmodified checkout → the new gate would be
  red for unrelated reasons; report with the failing tests.
- `serving/api.py`'s measured coverage stays near the unit value → the admin
  suites are not being collected; report before recording anything.
- Recording the profile would lower any existing floor (compare before/after for
  `profiles.unit` and the top-level totals) → STOP and report.
- CI runtime for the new job exceeds ~15 minutes on the runner → prefer a scoped
  suite (serving + storage + integration) over the full tree; report the choice.

## Maintenance notes

- Two profiles now exist on purpose: `unit` = fast local gate; `full` = CI truth
  for e2e-covered modules. Any future Makefile change must keep the profile/artifact
  pairing consistent (this is the thing that broke silently before).
- Reviewer should scrutinise: that the recorded `full` numbers were produced by
  the *same* selection CI runs (the target's command and the job's command must
  not drift).
- **Deferred:** the `serving/api.py` split, now measurable. Unblocked by this
  plan; it needs its own plan with the ratchet floor in place.
- **Deferred:** instrumenting `make test-e2e` (pipeline e2e) for the same reason.
  Unblocked by a decision that its git/npx harness is worth measuring.
