# Plan 155: The Stage-4 critic must evaluate — derive `average` from the seven scores

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat bc3b38a4..HEAD -- news_collector/components/editorial/ai_editor.py tests/unit/editorial/ docs/editorial_quality_system.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW-MED (parser semantics; the approval rule itself must not change)
- **Depends on**: plan 154 (DONE, merged `cfd8e252` — the canary that proved the defect); **sequence after PR #373 merges** (it touches the same parser/validator)
- **Category**: bug (a gate that silently abstains)
- **Planned at**: commit `bc3b38a4`, 2026-10-19

## Why this matters

The Stage-4 editorial critic is a publication gate. Issue **#366** required
real-provider evidence for it; plan 154 built the canary and its **first real
local run** (evidence commented on #366) returned **UNVERIFIED**:

```json
{"status":"UNVERIFIED","provider":"local","model":"qwen3-next:80b-a3b-instruct-q4_K_M",
 "transport_ok":true,"json_parsed":false,"error_kind":"parse_error","latency_ms":143329,
 "response_chars":536,"synthetic":true}
```

Root cause (2/2 samples): the model returned a complete verdict — booleans, seven
integer scores, feedback — but the parser **rejected it for arithmetic**:
`ValueError: average does not match the seven criterion scores`. The critic then
fails open, so **no verdict exists and the gate does nothing** — in the default
local path, the editorial critic is effectively switched off.

`average` is *derived data*: the mean of the seven scores the model already
provided. Requiring the model to reproduce that mean to ±0.11 turns its weakest
skill (arithmetic) into a hard gate on its strongest output (the scores). The fix
is to derive it.

## Current state

- `news_collector/components/editorial/ai_editor.py`:
  - `_parse_editorial_critic_result` (`:236`) — `required_keys` includes
    `"average"`, then calls the two helpers below.
  - `_parse_editorial_critic_average` / `_parse_editorial_critic_score_values`
    (`:190-208`):

```python
    average = _parse_editorial_critic_average(result)
    scores = _parse_editorial_critic_score_values(result)
    calculated_average = sum(scores.values()) / len(_EDITORIAL_CRITIC_SCORE_KEYS)
    if abs(average - calculated_average) > 0.11:
        raise ValueError("average does not match the seven criterion scores")
    return average, scores
```

  - `_validate_editorial_critic_approval` (`:211-220`) — derives
    `meets_thresholds = average >= 7.0 and all(score >= 5) and rigor >= 6` and
    raises when `approved != meets_thresholds`. **Keep this rule as-is** (it is
    the actual gate); it must now use the derived average.
  - Plan 154's canary: `scripts/editorial_critic_canary.py` (real critic seam,
    sanitized evidence, `--provider local`).
- PR #373 (merged before this plan, per the sequencing note) may have added a
  `value_add_assessment` parameter to `_validate_editorial_critic_approval` and a
  per-article verdict reset in `process_article`. Locate by symbol; do not undo
  any of it.

## Commands you will need

| Purpose          | Command                                                                 | Provenance | Expected on success              |
|------------------|-------------------------------------------------------------------------|------------|----------------------------------|
| Install/baseline | `make bootstrap`                                                        | declared   | exit 0                           |
| Lint             | `make lint`                                                             | declared   | exit 0                           |
| Types + coverage | `make type`                                                             | declared   | exit 0                           |
| Unit suite       | `make test`                                                             | declared   | all pass                         |
| Editorial suite  | `.venv/bin/pytest tests/unit/editorial -q --no-cov`                      | declared   | all pass                         |
| Canary (local)   | `.venv/bin/python scripts/editorial_critic_canary.py --provider local`   | declared   | exit 0/1 (a verdict), never 2    |
| Ledger           | `make plans-ledger-check`                                               | declared   | `validate_plans_ledger: OK`      |

Provenance: all `declared`. Local Ollama is reachable on this machine
(`http://localhost:11434/api/tags` → 200) and the canary's first run completed in
~143 s, so give it a generous timeout.

## Scope

**In scope**:

- `news_collector/components/editorial/ai_editor.py` — the parser helpers only
  (`_parse_editorial_critic_result`, `_parse_editorial_critic_average`,
  `_parse_editorial_critic_score_values`) and the call into
  `_validate_editorial_critic_approval`
- `tests/unit/editorial/` — parser/agent tests for the new behaviour
- `docs/editorial_quality_system.md` / `docs/EDITORIAL_MODES.md` — only if they
  state the average-consistency rule

**Out of scope** (do NOT touch):

- `_validate_editorial_critic_approval`'s thresholds or the approval rule.
- The critic prompt in `config/prompts.yaml` (do not "fix" this by asking the
  model to do arithmetic better; deriving is deterministic and provider-agnostic).
- The canary script (plan 154 owns it).
- Any other parser in `ai_editor.py` (fact-check, editorial input, etc.).

## Git workflow

- Branch: `advisor/155-critic-average-derivation`
- Conventional commits, e.g.
  `fix(editorial): derive the critic average from its scores (plan 155)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline and reproduce the shape

`make bootstrap`, `make lint`, `make test`, `make type`,
`.venv/bin/pytest tests/unit/editorial -q --no-cov`, and one canary run
(`--provider local`). Record the canary's exit code and evidence (it should be
UNVERIFIED / `parse_error` today).

**Verify**: gates green; the canary reproduces UNVERIFIED (if it returns a
verdict, STOP — the premise changed).

### Step 1: Derive the average

1. In `_parse_editorial_critic_result`, remove `"average"` from
   `required_keys` (the model no longer has to emit it).
2. In `_parse_editorial_critic_result` (or the helper), compute
   `average = round(sum(scores.values()) / len(_EDITORIAL_CRITIC_SCORE_KEYS), 2)`
   from the validated scores and use **that** value for the approval rule.
3. If the model *did* supply an `average` and it differs from the derived value
   by more than 0.11, log it at debug/info as model arithmetic drift — **never
   reject** on that basis. (Read the module's logging convention first; keep it
   cheap and non-noisy.)
4. Keep `_validate_editorial_critic_approval` unchanged (same thresholds, same
   contradiction check) — it now receives the derived average.

**Verify**: `.venv/bin/pytest tests/unit/editorial -q --no-cov` → all pass after
the test updates in Step 2.

### Step 2: Pin the behaviour

Add/extend tests in `tests/unit/editorial/`:

- **The canary's shape (regression)**: a verdict whose `average` is off by >0.11
  from the score mean **parses** and yields the derived average (this test must
  fail on the pre-change code).
- **Missing average**: a verdict without an `average` key parses (derived).
- **Scores still validated**: missing/out-of-range/non-integer scores are still
  rejected (the fail-open path, unchanged).
- **Approval rule unchanged**: `approved` contradicting the derived thresholds is
  still rejected.
- **Agent-level**: `_critic_editorial_pass` with a stubbed provider returning the
  canary's shape stores a verdict (does not fail open) — model the existing
  critic tests.

**Verify**: the regression test fails on the base source (prove once), then
passes; `.venv/bin/pytest tests/unit/editorial -q --no-cov` green.

### Step 3: Prove it with the canary (the whole point)

Run `.venv/bin/python scripts/editorial_critic_canary.py --provider local` **twice**
and record both evidence records + exit codes. Expected: **PASS (0) or FAIL (1)**
— a real verdict. `UNVERIFIED (2)` means the fix did not close the class → STOP
and report the new `error_kind`/root cause (do not loosen the parser further
without a decision).

**Verify**: two runs with status PASS/FAIL; the JSON's `verdict_fields` shows
`approved`, `average`, and the seven scores.

### Step 4: Document and hand the evidence back

- If the docs state the average-consistency rule, update them to "the average is
  derived from the scores; a differing model value is logged, not rejected".
- Put both sanitized evidence records + exit codes in your report; the reviewer
  will comment on #366 and close it if the evidence is conclusive.

**Verify**: `make docs-check` exits 0.

## Test plan

As in Step 2, plus the two real canary runs. No test depends on the network.

**Verify**: `make test && make type && make test-boundaries` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` exit 0
- [ ] The regression test (average off by >0.11) fails on the pre-change source and passes after
- [ ] `average` is derived for every parsed verdict; the model's value is never a rejection reason
- [ ] The approval rule (thresholds + contradiction) is unchanged
- [ ] Two canary runs return PASS or FAIL (not UNVERIFIED), with the sanitized evidence recorded
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 155 updated by the reviewer; `make plans-ledger-check` → OK

## STOP conditions

- The canary returns a verdict on the unmodified code (premise gone) → report.
- After deriving the average, the approval rule rejects the model's `approved`
  flag for the canary verdict (a *contradiction*, not arithmetic) → report the
  scores and the flag; the fix for that is a policy decision, not a parser tweak.
- The canary still returns UNVERIFIED for a different reason → report the
  `error_kind` and stop.
- The local model is unreachable during the run → record UNVERIFIED and stop;
  do not pull models.

## Maintenance notes

- The invariant: **derived values are derived** — never let a model's arithmetic
  decide whether a gate runs. If a new derived field is added (e.g. a weighted
  average), compute it here too.
- Reviewer should scrutinise: the approval thresholds are byte-identical, and the
  contradiction path still fails open (pinned).
- **Deferred:** an abstention metric/dashboard (how often the critic fails open,
  by reason). Unblocked by a decision on where that counter should live.
