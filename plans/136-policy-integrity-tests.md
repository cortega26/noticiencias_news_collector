# Plan 136: Test the editorial policy integrity gate for real

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- news_collector/editorial/policy.py news_collector/editorial/policy_manifest.json news_collector/logic/workflows/refinery_engine.py tests/test_policy_integrity.py tests/test_editorial_policy_enforcement.py tests/unit/logic/workflows/test_refinery_engine.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

The editorial policy manifest is the repo's tamper-detection control for the
thresholds that decide whether an article publishes or is blocked
(`config.toml` sets `policy_integrity_mode = "enforced"`, and
`refinery_engine.py:206-224` re-raises on failure). **No test executes the real
verification code.** Every test that mentions it patches the method out
(`patch.object(EditorialPolicy, "verify_integrity", ...)`), and a grep shows the
real method has exactly one production caller. A change that neuters the gate —
an early `return`, a wrong manifest path, comparing a value to itself, dropping
the canonicalization — leaves the whole suite green. Under `docs/AGENTS.md` §4.1
("assert on the fakes" is a rejection reason) this is exactly the kind of
unearned green the repo's own rules forbid.

## Current state

- `news_collector/editorial/policy.py`
  - `:54-87` `compute_sha256()` — canonical `key=value|key=value` string over
    `mode, critic_threshold, auditor_threshold, require_caveats,
    require_no_hallucinations`, sha256 hexdigest.
  - `:89-128` `verify_integrity(manifest_path)` —
    - missing manifest → `raise IntegrityError(...)`
    - version mismatch → `logger.warning` only (no raise)
    - hash mismatch → `logger.critical` + `raise IntegrityError(...)`
    - sets `self.policy_sha256 = computed_hash` on success
    - wraps unexpected errors into `IntegrityError`.
  - `from_mode` builds the dataclass (used at `refinery_engine.py:205`).
- `news_collector/logic/workflows/refinery_engine.py:206-224` — wiring:
  `integrity_mode` = `config.app.policy_integrity_mode` (default `"enforced"`);
  `"disabled"` skips, `"warn"` logs, enforced re-raises.
- Existing tests (all patch the method — none exercise it):
  `tests/test_policy_integrity.py:29-33,45,70,105`,
  `tests/test_editorial_policy_enforcement.py:43`,
  `tests/unit/logic/workflows/test_refinery_engine.py:1132`.
- The manifest lives at `news_collector/editorial/policy_manifest.json`.

## Commands you will need

| Purpose          | Command                                                             | Provenance | Expected on success          |
|------------------|---------------------------------------------------------------------|------------|------------------------------|
| Install/baseline | `make bootstrap`                                                    | declared   | exit 0                       |
| Lint             | `make lint`                                                         | declared   | exit 0                       |
| Types + coverage | `make type`                                                         | declared   | exit 0                       |
| Unit suite       | `make test`                                                         | declared   | all pass                     |
| Focused tests    | `.venv/bin/pytest tests/test_policy_integrity.py tests/unit/editorial -q --no-cov` | declared | all pass      |
| Ledger           | `make plans-ledger-check`                                           | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared`. A `declared` command failing on an unmodified
checkout is a broken baseline — STOP and report.

## Scope

**In scope**:

- New: `tests/unit/editorial/test_policy_integrity_real.py`
- `tests/test_policy_integrity.py` — only if you replace one mocked case with the
  real one (keep the engine-wiring cases that legitimately mock)
- No production code changes. If you conclude production code must change, STOP.

**Out of scope** (do NOT touch):

- `news_collector/editorial/policy.py` behaviour or the manifest file content
  (the committed hash must stay valid — verify it, do not regenerate it).
- `refinery_engine.py`.
- The mocked tests' intent (they cover engine branching, which is fine).

## Git workflow

- Branch: `advisor/136-policy-integrity-tests`
- Conventional commit, e.g. `test(editorial): exercise the real policy integrity gate (plan 136)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run the `Install` row, then the remaining table commands on the unmodified
checkout. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Confirm the gap yourself before writing anything

1. Run `.venv/bin/python -c "from news_collector.editorial.policy import EditorialPolicy; ..."`
   to confirm the committed manifest validates (compute the hash for
   `from_mode("standard")` and compare against
   `news_collector/editorial/policy_manifest.json`'s `sha256`). Record the result
   in the ledger row (do not print the full hash outside the repo).

**Verify**: your command prints a boolean "manifest matches" result.

### Step 2: Write the real tests

Create `tests/unit/editorial/test_policy_integrity_real.py` with real
`tmp_path` manifests (no mocks of the subject):

- **match**: manifest written with `{"version": policy.version, "sha256": policy.compute_sha256()}`
  → `verify_integrity(path)` returns without raising and sets `policy.policy_sha256`.
- **tamper**: take the matching manifest and change one policy field (e.g.
  `critic_threshold`) → `pytest.raises(IntegrityError)`, and assert the message
  mentions the integrity failure.
- **missing file**: non-existent path → `IntegrityError`.
- **version mismatch**: correct hash, different `version` → no raise
  (warning path, assert with `caplog`).
- **malformed manifest JSON**: write garbage → `IntegrityError` (not a raw
  `JSONDecodeError`).
- **determinism**: `compute_sha256()` is stable across two constructions of the
  same policy and changes when any of the five hashed fields changes (this pins
  the canonicalization that a future edit could quietly break).

**Verify**: `.venv/bin/pytest tests/unit/editorial/test_policy_integrity_real.py -q --no-cov` → all pass.

### Step 3: Prove the tests can fail

2. Temporarily change one line of `policy.py` (e.g. make `verify_integrity`
   return early) and confirm the suite goes red; then revert with `git checkout --`.
   Record the observed failure names.

**Verify**: the temporary change produced test failures; `git diff` is clean afterwards.

### Step 4 (optional, only if trivial): engine-level end-to-end

3. If `tests/unit/logic/workflows/test_refinery_engine.py` already has a fixture
   that builds a real `RefineryEngine` with a real config, add one case with
   `policy_integrity_mode="enforced"` and a tampered manifest path → the engine
   raises at construction. If that requires new heavyweight fixtures, skip it and
   say so in the ledger row (the unit tests above already cover the gate).

**Verify**: `make test` → all pass.

## Test plan

As above; ~6 tests, all real-file based, order-safe, no network. Model the file
layout on `tests/unit/editorial/`'s existing modules.

**Verify**: `make test` → green; `make type` → ratchet unchanged (new file in
`tests/` is not measured for coverage; if the ratchet complains about a changed
file, note that `tests/` is excluded).

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test` exit 0
- [ ] `grep -c "verify_integrity" tests/unit/editorial/test_policy_integrity_real.py` ≥ 1 and the file contains **no** `patch.object(EditorialPolicy`
- [ ] Step 3's temporary-break proof recorded
- [ ] Committed manifest still validates (Step 1 result recorded)
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 136 updated; `make plans-ledger-check` → OK

## STOP conditions

- The Step 1 check reports the committed manifest does **not** match the computed
  hash → that is a live integrity failure; STOP and report immediately.
- The excerpts do not match the live code (drift).
- Writing the tests would require changing `policy.py` (e.g. it has no way to be
  constructed with a bad field) — report the smallest production seam you need
  instead of changing behaviour.

## Maintenance notes

- The determinism test is the one to keep honest: any new field added to
  `compute_sha256` must be added to both the test's field list and the manifest
  regeneration step, or the gate will fail in production for everyone.
- Reviewer should scrutinise: no assertion on log text that a refactor would
  legitimately change (assert on `IntegrityError` type and the fact of a warning,
  not exact wording).
- **Deferred:** mutation coverage for `policy.py` (it is a pure module that
  decides publish/block). Unblocked by plan 140 landing its harness.
