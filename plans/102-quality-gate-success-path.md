# Plan 102: Cover the quality-gate success path (not only failure exits)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- scripts/quality_gate.py tests/test_quality_gate.py quality_gate/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`make quality-gate` is the snapshot-first publication gate, but its entire test
file (31 lines) asserts only two failure exits. Nothing proves a valid golden
set passes or that snapshot content is actually compared — a silently-neutered
validator (always-exit-1-on-empty, skip-comparison-otherwise) satisfies the
suite. Two focused tests close the hole: a tmp-golden success case and a
tampered-snapshot case asserting a distinct failure reason.

## Current state

The relevant files, each with one line on its role:

- `scripts/quality_gate.py` — `QualityGateValidator` (`GOLDEN_DIR` at line 11, `run()` at 19, failures at 22-49, `sys.exit(0)` at 52, `_validate_case` at 54, `_check_rules` at 110)
- `tests/test_quality_gate.py` — the whole file is 31 lines, both tests assert `exc_info.value.code == 1`
- `quality_gate/golden/` — committed golden cases (read for fixture shape)

Excerpts of the code as it exists today:

`tests/test_quality_gate.py:1-31` (entire file):

```python
"""Tests for the snapshot quality gate."""

from pathlib import Path

import pytest

from scripts import quality_gate


def test_empty_golden_directory_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 1


def test_ollama_configuration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "case").mkdir()
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)
    monkeypatch.setenv("OLLAMA_API_URL", "http://localhost:11434")

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 1
```

`scripts/quality_gate.py:11-52` (structure):

```python
GOLDEN_DIR = PROJECT_ROOT / "quality_gate" / "golden"
class QualityGateValidator:
    def __init__(self): ...
    def run(self):
        ...
        if not GOLDEN_DIR.exists(): ... sys.exit(1)
        cases = sorted([d for d in GOLDEN_DIR.iterdir() if d.is_dir()])
        ... # empty → sys.exit(1); per-case failures → sys.exit(1)
        ...
        sys.exit(0)
    def _validate_case(self, case_dir: Path) -> bool: ...
```

Repo conventions that apply here:

- The existing tests' pattern (monkeypatched `GOLDEN_DIR` → `tmp_path`, `pytest.raises(SystemExit)`) is the exemplar — extend it, don't restructure.
- `make quality-gate` needs no LLM (snapshot-first); tests must not need one either (no network, no Ollama — watch the second existing test's `OLLAMA_API_URL` usage and stay hermetic).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Gate      | `make quality-gate`      | declared   | exit 0 (proves the gate itself still passes) |

## Scope

**In scope** (the only files you should modify):

- `tests/test_quality_gate.py` (new tests only)

**Out of scope** (do NOT touch, even though they look related):

- `scripts/quality_gate.py` — under test, not under change. If the validator is untestable as-is (e.g. hardcoded paths beyond `GOLDEN_DIR`, network calls in `run()`), STOP and report rather than refactoring it to fit the tests.
- `quality_gate/golden/` committed fixtures — read-only reference for crafting tmp fixtures.
- `make quality-gate-refresh` (LLM regeneration) — explicitly out; never run it (it overwrites committed snapshots).

## Git workflow

- Branch: `advisor/102-quality-gate-success-path`
- Conventional commits, e.g. `test(quality): cover quality-gate success and tamper paths`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. Also run
`make quality-gate` once and record its output (it should pass on the clean
tree — if it doesn't, record the exact failure; that's context, not a STOP).
Read `scripts/quality_gate.py` in full (`_validate_case`, `_check_rules`) and
one committed golden case directory to learn the minimal valid fixture shape.

**Verify**: you can describe the golden-case anatomy (input files + snapshot files + what `_check_rules` compares) in two sentences.

### Step 1: Add the success-path test

In `tests/test_quality_gate.py`, following the existing monkeypatch pattern:

```python
def test_valid_golden_directory_passes(tmp_path, monkeypatch):
    # build minimal valid case under tmp_path per the anatomy from Step 0
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()
    assert exc_info.value.code == 0
```

Copy the fixture shape from the smallest committed golden case (read, don't import, its files). Keep it hermetic: no env vars, no network, no Ollama.

**Verify**: `.venv/bin/python -m pytest tests/test_quality_gate.py -q` → 3 pass.

### Step 2: Add the tampered-snapshot test

Duplicate the Step 1 fixture, then tamper exactly one compared byte (e.g. flip one character in the snapshot the validator compares). Assert `SystemExit` with code 1 AND that the failure output names the case/rule distinctly from the empty-golden and ollama-config failures (capture stdout via `capsys` and assert the distinguishing token — read `run()`'s messages to pick it; if all three failures print indistinguishable text, assert on the exit path differently: monkeypatch/spy `_validate_case` return or `_check_rules` — and NOTE the indistinguishability in your report as a follow-up).

**Verify**: new test passes; prove sensitivity by hand: run the same test against the untampered copy and watch it pass (i.e. the tamper is what flips the outcome).

### Step 3: Run the full gates

**Verify**: `make lint && make type && make test && make quality-gate` → all exit 0.

## Test plan

- New `test_valid_golden_directory_passes` (exit 0 on valid goldens).
- New tampered-snapshot test (exit 1 with case-specific reason).
- Existing two failure tests unchanged; `make quality-gate` green proves no fixture drift.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make quality-gate` all exit 0
- [ ] Success-path and tamper tests exist and pass (file has ≥4 tests)
- [ ] Tamper sensitivity demonstrated by hand (tampered → fail, untampered → pass)
- [ ] No change to `scripts/quality_gate.py` or `quality_gate/golden/` (`git diff --name-only` shows only the test file)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- The validator needs network/Ollama for even the success path (then hermetic tests are impossible without refactoring — report, don't refactor).
- The golden-case anatomy requires committed-snapshot coupling that tmp fixtures can't reproduce (report the coupling).
- NEVER run `make quality-gate-refresh` — it overwrites committed snapshots. If a step seems to require it, stop instead.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If new golden cases or rules are added, extend the tmp fixture to cover the new rule — the success test should grow with the gate.
- Reviewers: the tamper test's sensitivity proof is the load-bearing evidence; ask for it explicitly in review.
- **Deferred:** distinguishing log messages per failure mode (if Step 2 finds them indistinguishable) — trivial follow-up, needs an operator nod on message wording.
