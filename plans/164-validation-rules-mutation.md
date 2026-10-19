# Plan 164: Raise the `validation/rules.py` mutation floor

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 7bf0c444..HEAD -- news_collector/validation/rules.py pyproject.toml tests/unit/validation/`
> If `rules.py` or the existing validation tests changed since this plan was
> written, read them before writing tests; on a mismatch with the excerpts,
> STOP.

## Status

- **Priority**: P2 (quality gate's core rules can be broken silently)
- **Effort**: M
- **Risk**: LOW-MEDIUM (test-only; a wrong test can pin wrong behaviour)
- **Depends on**: 140 (widened mutation scope and set the 56 floor)
- **Category**: tests / mutation
- **Planned at**: commit `7bf0c444`, 2026-10-19

## Why this matters

Plan 140 widened mutation testing to nine modules and set
`[tool.mutation.floors]` to each measured score minus ~3. `validation/rules.py`
got the **lowest floor (56 %)** with **92 survivors**: behaviour changes in the
validation gate that no test notices. Rules are the thing that decides whether
an article is published, so a silently weakened rule is a product bug.

The goal is **not** 100 %. It is to kill the survivors that encode rule
behaviour (pass/fail, thresholds, rule selection, evidence fields) and to
document the equivalent/string-only ones, then raise the floor to what is
actually achieved so a regression fails the gate.

## Current state

- `pyproject.toml` — `[tool.mutation.floors]` has
  `"news_collector/validation/rules.py" = 56`.
- `news_collector/validation/rules.py` — 292 lines, 17 functions; rules are
  evaluated per article and produce validation issues.
- `scripts/mutation_score.py` — score = detected / (detected + survived +
  untested + suspicious); `--check` fails below a floor and also fails a floor
  with no results. Survivors and "no tests" mutants both count against the
  score.
- `make mutation` — installs mutmut into `.mutlib`, `rm -rf mutants`, runs the
  full configured scope (`--max-children 4`) and calls
  `scripts/mutation_score.py --check`. Plan 140 measured ~141 s.
- **The `mutants/` directory in the checkout is stale** (2 meta files from an
  unrelated run): `scripts/mutation_score.py --check` currently reports
  "no mutation results" for most floors. A **fresh `make mutation`** is
  required before analysing survivors.
- Existing tests: `tests/unit/validation/` (read them before adding; reuse
  fixtures and the issue-shape assertions).

## Commands you will need

| Purpose        | Command                                              | Provenance | Expected |
|----------------|------------------------------------------------------|------------|----------|
| Install        | `make bootstrap`                                     | declared   | exit 0   |
| Mutation       | `make mutation`                                      | declared   | exit 0, all 9 floors pass |
| Survivors      | `PYTHONPATH=.mutlib .venv/bin/python -m mutmut show <id>` | declared | diff of one mutant |
| Focused tests  | `.venv/bin/pytest tests/unit/validation -q --no-cov` | declared   | all pass |
| Lint/types     | `make lint` / `make type`                            | declared   | exit 0   |
| Unit suite     | `make test`                                          | declared   | all pass |

Provenance: all `declared`.

## Scope

**In scope**:

- `tests/unit/validation/` — new/extended tests (a new file is fine)
- `pyproject.toml` — **only** the `validation/rules.py` floor value

**Out of scope**:

- `news_collector/validation/rules.py` itself (do **not** change behaviour to
  make mutants die; if a mutant reveals a real bug, STOP and report it).
- Other modules' floors.
- Chasing string/logging/repr mutants.

## Steps

### Step 0: Fresh baseline

1. `make bootstrap`; `make mutation` (long timeout, ~3-10 min). Record the
   per-module table and specifically the `validation/rules.py` line
   (detected / survived / untested / score).
2. List the surviving mutant ids for that module (mutmut writes them under
   `mutants/`; `mutmut show` prints each diff). **Do not paste secret values or
   unrelated source into the report** — rule names and function names are enough.

**Verify**: the run completes; the module's score is ~56-60 %.

### Step 1: Classify the survivors

3. Group survivors into:
   - **behavioural** — changes a rule's decision, threshold, message-selection
     branch, or issue payload;
   - **equivalent** — same observable behaviour (e.g. formatting, log text,
     defensive branches that cannot be reached with the public API).
4. Record the counts in NOTES. Do not write tests for equivalent survivors.

**Verify**: every survivor id is classified.

### Step 2: Kill the behavioural survivors

5. Write table-driven tests in `tests/unit/validation/` that pin each
   behavioural class:
   - each rule id fires only on its condition and not on a clean article;
   - boundary values on either side of every numeric/string threshold;
   - rule ordering / multi-issue aggregation;
   - the issue payload fields callers consume (`rule_id`, severity/level,
     message/evidence) — assert the exact field values, not truthiness.
6. Run the focused tests after each group; never weaken an existing assertion.

**Verify**: focused tests pass; each new test fails if its rule's branch is
mutated (mutmut re-run in Step 3 is the proof).

### Step 3: Re-measure and raise the floor

7. `make mutation` again. Record the new module score.
8. Raise the floor in `pyproject.toml` to **`floor(new_score) - 3`** (the plan-140
   convention), never below **56** (a floor only rises). If the achieved score
   is ≤ 59, keep 56 and report why (equivalent-dominated).
9. Confirm all nine floors pass with the new value.

**Verify**: `make mutation` exit 0; the new floor is justified by the measured
score.

### Step 4: Gates

10. `make lint`, `make type` (**post-commit only**), `make test`,
    `make test-boundaries`, `make plans-ledger-check`.
11. Report the final table (before → after) and the survivor classes left.

**Verify**: all exit 0.

## Test plan

- New tests are the deliverable; each must assert observable behaviour of a
  rule (decision + payload), not implementation details.
- Mutation re-run is the falsifiability proof: the score must rise.

**Verify**: `make test` green; `make mutation` green with the raised floor.

## Done criteria

- [ ] Fresh mutation run recorded; survivors classified
- [ ] Behavioural survivors covered by tests; equivalent ones documented
- [ ] Floor raised to measured − 3 (≥ 56); all nine floors pass
- [ ] No production code changed
- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] `git diff --name-only main...HEAD` lists only tests + `pyproject.toml`
- [ ] Ledger row 164 updated by the reviewer

## STOP conditions

- A survivor reveals a **real bug** in `validation/rules.py` → stop and report
  the rule, the input, and the wrong decision; do not encode the bug in a test.
- The module's score after reasonable tests is still ≤ 56 (equivalent-dominated)
  → report the classification; keep the floor and do not force it up.
- `make mutation` cannot run (install/network) → report the exact failure.
- Re-measuring would require changing the mutation scope or test selection.

## Maintenance notes

- Floors are raised **after** the fact (measured − 3); never set a floor above a
  measured score to "motivate" work.
- If a later refactor makes survivors equivalent, re-measure and lower? No:
  equivalent survivors still count in the score; only remove/replace tests with
  evidence.
