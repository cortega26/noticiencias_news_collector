# Plan 140: Mutation floors must cover the modules that decide identity and health

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- pyproject.toml scripts/mutation_score.py .github/workflows/mutation.yml Makefile tests/ news_collector/logic/workflows/publication_identity.py news_collector/editorial/health_scope.py news_collector/validation/rules.py news_collector/editorial/categories.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

`docs/AGENTS.md` §4.1 says a test earns its place when it can fail for a real
reason, and that "new pure policy modules that decide admission, identity,
classification or grounding should be added to `[tool.mutmut]` with a floor once
their score is known". Today only five modules are mutated, and the two most
consequential pure-policy modules in the repo are missing:

- `news_collector/logic/workflows/publication_identity.py` — the LAW-B5 identity
  implementation (canonical slug/date derivation). Line coverage looks healthy;
  nothing proves a test would *notice* an inverted comparison or a dropped branch.
- `news_collector/editorial/health_scope.py` — self-described "single definition
  of health-related article", gating the health-disputed publish block.
- `news_collector/validation/rules.py` — pure validation rules (docstring:
  "Side effects: None").
- `news_collector/editorial/categories.py` — category normalization.

Mutation also runs only on a weekly cron (`mutation.yml`), so a surviving mutant
is discovered up to seven days later, never on the PR that introduced it.

## Current state

- `pyproject.toml:200-210`:

```toml
[tool.mutmut]
source_paths = [
    "news_collector/collectors/admission.py",
    "news_collector/infrastructure/llm/failure_kinds.py",
    "news_collector/editorial/grounding.py",
    "news_collector/observability/llm_run_report.py",
    "news_collector/utils/url_canonicalizer.py",
]
pytest_add_cli_args_test_selection = [ ...18 test files... ]
```

- `pyproject.toml:238-243` — `[tool.mutation.floors]` with one floor per module
  (admission pinned at 100, others 82-88).
- `Makefile:421-425` — `make mutation`: installs mutmut into `.mutlib`, wipes
  `mutants/`, runs `mutmut run --max-children 4`, then
  `scripts/mutation_score.py --check`.
- `.github/workflows/mutation.yml` — `schedule` (Mon 06:00) + `workflow_dispatch`,
  `timeout-minutes: 45`, runs `mutmut run --max-children 2` then the score check.
- Candidate modules exist and are small-to-medium: `publication_identity.py`
  (24.5 KB), `health_scope.py` (2.6 KB), `validation/rules.py` (10 KB),
  `editorial/categories.py` (4.8 KB).

## Commands you will need

| Purpose             | Command                                              | Provenance | Expected on success                     |
|---------------------|------------------------------------------------------|------------|-----------------------------------------|
| Install/baseline    | `make bootstrap`                                     | declared   | exit 0                                  |
| Lint                | `make lint`                                          | declared   | exit 0                                  |
| Types + coverage    | `make type`                                          | declared   | exit 0                                  |
| Unit suite          | `make test`                                          | declared   | all pass                                |
| Mutation (slow)     | `make mutation`                                      | declared   | score check passes for every floored module |
| Ledger              | `make plans-ledger-check`                            | declared   | `validate_plans_ledger: OK`             |

Provenance: all `declared`. `make mutation` is slow (minutes to tens of minutes)
and installs mutmut into `.mutlib` per the repo's own target — that is expected,
not a rule violation.

## Scope

**In scope**:

- `pyproject.toml` — `[tool.mutmut].source_paths`,
  `pytest_add_cli_args_test_selection`, `[tool.mutation.floors]`
- `.github/workflows/mutation.yml` — timeout/job shape only if the runtime needs it
- `docs/ci.md` and `docs/testing.md` — if they describe the mutation scope
- `tests/` — only if you must add a missing test that a surviving mutant exposes
  (prefer adding the test over lowering a floor; see Step 3)

**Out of scope** (do NOT touch):

- The existing five modules' floors (they are evidence-pinned; do not lower them).
- `mutation_smoke` tests.
- Any production module's behaviour (this plan measures; it only writes tests
  where a mutant proves a gap).

## Git workflow

- Branch: `advisor/140-mutation-coverage-widening`
- Conventional commit, e.g. `test(mutation): floor identity and health-scope modules (plan 140)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`, then `make mutation`
to confirm the current mutation gate is green **before** widening it. Red
baseline → STOP and report.

**Verify**: every command matches its expected result; record the current
per-module scores printed by `scripts/mutation_score.py --check`.

### Step 1: Add one module at a time and measure

1. Start with `news_collector/editorial/health_scope.py` (smallest). Add it to
   `source_paths` and add its test files to
   `pytest_add_cli_args_test_selection` (find them:
   `grep -rln "health_scope" tests/`).
2. Run `make mutation`; record the module's score from the output.
3. Repeat for `news_collector/validation/rules.py`, then
   `news_collector/editorial/categories.py`, then
   `news_collector/logic/workflows/publication_identity.py` (this one is the
   biggest — run it last).
4. After each addition, note the wall-clock time of `make mutation`. **STOP rule:**
   if the cumulative run approaches the CI job's 45-minute budget, stop adding
   modules, raise `timeout-minutes` in `mutation.yml` (up to 60) or split the job,
   and record the decision.

**Verify**: `make mutation` runs with the new modules included and prints a score per module.

### Step 2: Pin floors honestly

5. For each newly added module, add a floor equal to the measured score minus ~3
   points (matching the existing comment's convention at `pyproject.toml:236-238`).
   Never set a floor above the measured score.
6. If a module's measured score is very low (< 50), do not pin a low floor and
   move on — instead record it as a finding in the ledger row and add the
   missing tests that kill the cheapest survivors (up to ~1 day of work), then
   re-measure.

**Verify**: `scripts/mutation_score.py --check` (via `make mutation`) exits 0 with the new floors.

### Step 3: Kill the obvious survivors in identity

7. For `publication_identity.py` specifically, inspect the survivor list
   (`mutants/` after a run, or the mutmut cache output) and add focused tests for
   any survivor in the date-prefix parsing, the missing-slug branch, or the
   empty-id guard, modelled on the existing identity tests
   (`tests/unit/logic/workflows/` — find them with
   `grep -rln "publication_identity\|resolve_publication_identity" tests/`).
   Keep tests behavioural (LAW-B5: deterministic outputs), not implementation
   introspection.

**Verify**: the module's score improves; the new floor reflects the new score.

### Step 4: Make the cadence honest

8. If (and only if) the added modules keep the job well under its timeout, add a
   **path-filtered** PR trigger to `mutation.yml` for the pure modules only
   (e.g. `on: pull_request: paths: [news_collector/editorial/health_scope.py, news_collector/validation/rules.py, news_collector/editorial/categories.py]`)
   so a PR touching them gets the signal before merge. If runtime makes that
   impractical, keep cron-only and state the measured runtime in the ledger row.

**Verify**: the YAML parses; if you skipped the PR trigger, the reason is recorded.

## Test plan

- New tests only where a mutant proved a real gap (Step 3); each must fail
  against the mutated code and pass against the original (mutmut gives you the
  mutant to check with, or reproduce the mutation by hand once and revert).
- No new test targets or markers.

**Verify**: `make test` → green; `make mutation` → green with the new floors.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `[tool.mutmut].source_paths` includes the four new modules
- [ ] Every new module has a floor ≤ its measured score, with the measured score
      recorded in the ledger row
- [ ] `make mutation` exits 0 locally
- [ ] `mutation.yml` runtime decision recorded (timeout raised / job split / cron-only with reason)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 140 updated; `make plans-ledger-check` → OK

## STOP conditions

- The baseline `make mutation` is red before your change → record the failing
  module and STOP (widening a red gate is not meaningful).
- A candidate module's mutation run exceeds ~30 minutes on its own → keep it
  scheduled-only, report, and do not add the others until the budget question is
  answered.
- Killing survivors would require mocking half the system (AGENTS §7 refactor
  trigger) → report the refactor signal instead of contorting the tests.

## Maintenance notes

- Floors are noise-adjusted by ~3 points because mutmut timeout mutants flap —
  keep that convention; a flapping floor will be reverted by a future reviewer.
- Reviewer should scrutinise: that no existing floor was lowered, and that new
  tests assert behaviour (deterministic identity outputs), not private helpers.
- **Deferred:** a PR-time mutation job for all floored modules. Unblocked by
  reducing mutant runtime (e.g. `mutmut` per-module parallelism decisions).
