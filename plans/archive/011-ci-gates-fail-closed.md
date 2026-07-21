# Plan 011: Make the CI security & quality gates fail **closed** on missing/empty inputs

> **Executor instructions**: Follow step by step; run every verification command
> and confirm the expected result before moving on. Honor STOP conditions. Update
> this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- scripts/security_gate.py scripts/quality_gate.py`
> If either changed, re-confirm the "Current state" excerpts before editing; on a
> structural mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (CI correctness / security)
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

Two CI gates **pass when they should fail** because they treat absent/empty input as "nothing wrong":

1. **`security_gate.py`** — when a scanner report is **missing or empty**, the loader returns an empty structure, the finder iterates zero items, and the gate prints "No findings" and **exits 0**. In CI (`.github/workflows/ci.yml:180,209,232,234`) the gate is invoked with a report path produced by a prior scan step. If that step fails to write the report (scanner crash, wrong path, empty file), the gate **silently passes** — the security scan is effectively disabled with no signal.
2. **`quality_gate.py`** — if `GOLDEN_DIR` exists but contains **no case directories**, the loop runs zero times, `failed_cases` stays empty, and it prints "QUALITY GATE PASSED" and **exits 0**. Deleting/mis-pathing the golden snapshots makes the gate vacuously pass.
3. **`quality_gate.py:30-31`** — a **dead safety guard**: `if os.getenv("OLLAMA_API_URL"): pass`. The comment says "ensure Ollama is not accidentally used" (the gate is meant to run with no LLM), but the body is a no-op, so the guard does nothing.

A gate that can't fail is worse than no gate — it manufactures false confidence. Note: a **malformed** (non-empty, invalid-JSON) report already fails correctly, because `json.JSONDecodeError` subclasses `ValueError` and is caught at `security_gate.py:331`. The gap is specifically **missing/empty**.

## Current state

### `scripts/security_gate.py`

```python
# security_gate.py:127-135
def _load_json(report_path: Path, default: Any) -> Any:
    if not report_path.exists():
        return default            # <-- missing file → default ({}) → no findings → pass
    content = report_path.read_text().strip()
    if not content:
        return default            # <-- empty file → same
    return json.loads(content)

# pip_audit_findings (186), bandit_findings (210): data = _load_json(report_path, {})
#   then iterate data.get("dependencies"/"results", []) → [] when default → 0 findings
# main (315-350): findings empty → status "pass" → return 0
```

`_load_json_lines` (138-168, used by `gitleaks_findings`) similarly returns `[]` for missing/empty. **Important nuance**: for **gitleaks**, an empty report is the *normal "no secrets found"* output, so empty-gitleaks = clean is legitimate. For **pip-audit** and **bandit**, a clean scan still writes a valid JSON document (`{"dependencies": [...]}` / `{"results": []}`), so a *missing or empty* file means the scan did not run → should fail.

The gate is invoked per-tool: `main(argv)` parses `tool` (`pip-audit|bandit|gitleaks`), `report` (Path), `--severity`. It already has a clean failure channel: `except ValueError as exc: print(...); return 1` (331-333).

Tests: `tests/test_security_gate.py` (cases listed via `grep "def test_"`) covers allowlist/severity/expiry but **has no missing/empty-report case**.

### `scripts/quality_gate.py`

```python
# quality_gate.py:19-44 (QualityGateValidator.run)
if not GOLDEN_DIR.exists():
    print(f"❌ Golden directory not found: {GOLDEN_DIR}")
    sys.exit(1)

cases = sorted([d for d in GOLDEN_DIR.iterdir() if d.is_dir()])
failed_cases = []

# Security: Ensure Ollama is not accidentally used
if os.getenv("OLLAMA_API_URL"):
    pass                          # <-- DEAD no-op guard (lines 30-31)

for case_dir in cases:           # <-- empty cases → loop skipped
    ...
if failed_cases:
    sys.exit(1)
else:
    print("✅ QUALITY GATE PASSED. All snapshots valid.")
    sys.exit(0)                  # <-- reached vacuously when cases == []
```

No dedicated test file for `quality_gate.py` (`find tests -iname '*quality_gate*'` is empty).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Security-gate tests | `.venv/bin/pytest tests/test_security_gate.py -q` | all pass |
| Manual: missing report fails | `.venv/bin/python scripts/security_gate.py bandit /tmp/does_not_exist.json --severity HIGH; echo $?` | non-zero |
| Manual: empty golden passes-vacuously is fixed | see Step 3 | exit 1 |
| Lint / type | `make lint` (mypy excludes scripts/, so `make type` won't cover these) | exit 0 |
| Fast suite | `make test` | all pass |

## Scope

**In scope:**
- `scripts/security_gate.py` — fail closed on missing/empty report for pip-audit & bandit
- `scripts/quality_gate.py` — fail closed on empty golden set; fix the dead OLLAMA guard
- `tests/test_security_gate.py` — add missing/empty cases
- `tests/test_quality_gate.py` (create) — empty-golden case

**Out of scope:**
- gitleaks' empty=clean semantics (legitimate — do not change).
- The allowlist/severity logic.
- Refactoring the gates beyond the fail-closed fix.
- CI workflow YAML (the scripts are the right layer to fix).

## Git workflow

- Branch: `advisor/011-ci-gates-fail-closed`
- Commits: one for security_gate, one for quality_gate (+ tests).
- Do NOT push or open a PR.

## Steps

### Step 1: `security_gate.py` — require a real report for pip-audit & bandit

Add a strict loader that raises when the report is missing/empty, and use it (only) for pip-audit and bandit. Keep `_load_json` as-is for any lenient use, or add a `required` flag. Suggested shape:

```python
def _load_required_json(report_path: Path, tool: str) -> Any:
    if not report_path.exists():
        raise ValueError(
            f"{tool} report not found at {report_path} — scan did not run; failing closed."
        )
    content = report_path.read_text().strip()
    if not content:
        raise ValueError(
            f"{tool} report at {report_path} is empty — scan produced no output; failing closed."
        )
    return json.loads(content)  # JSONDecodeError (a ValueError) already fails closed in main()
```

In `pip_audit_findings` and `bandit_findings`, replace `data = _load_json(report_path, {})` with `data = _load_required_json(report_path, "<tool>")`. The raised `ValueError` is already caught in `main` (331-333) and returns 1. Leave `gitleaks_findings`/`_load_json_lines` unchanged (empty = clean is correct for gitleaks).

**Verify:** `.venv/bin/python scripts/security_gate.py bandit /tmp/nope.json --severity HIGH; echo $?` → prints a "report not found … failing closed" message and a **non-zero** exit. Same for an empty file: `: > /tmp/empty.json && .venv/bin/python scripts/security_gate.py pip-audit /tmp/empty.json; echo $?` → non-zero.

### Step 2: `quality_gate.py` — fail closed on empty golden set; fix the dead guard

After computing `cases`, fail if there are none:

```python
cases = sorted([d for d in GOLDEN_DIR.iterdir() if d.is_dir()])
if not cases:
    print(f"❌ QUALITY GATE FAILED. No golden cases found in {GOLDEN_DIR}.")
    sys.exit(1)
```

Replace the dead OLLAMA guard (lines 30-31) with a real check that matches its stated intent (the gate must run without an LLM):

```python
if os.getenv("OLLAMA_API_URL"):
    print("❌ QUALITY GATE: OLLAMA_API_URL is set; the snapshot gate must run without an LLM.")
    sys.exit(1)
```

(If you discover the gate is legitimately allowed to run with `OLLAMA_API_URL` set in some workflow — check `.github/workflows/` and the Makefile — then instead of exiting, downgrade to a printed warning and note it. Do not silently `pass`.)

**Verify:** do **not** touch the real `quality_gate/golden` fixtures. Confirm this
behavior with the monkeypatched test in Step 3 (it points `GOLDEN_DIR` at an empty
`tmp_path`). For a quick manual smoke check, run the validator against a temp dir
via a throwaway snippet that monkeypatches the module constant — never rename or
delete the committed golden set:

```bash
.venv/bin/python -c "import scripts.quality_gate as q, pathlib, tempfile; \
q.GOLDEN_DIR = pathlib.Path(tempfile.mkdtemp()); \
import sys; \
try: q.QualityGateValidator().run()
except SystemExit as e: print('exit', e.code)"
```
→ prints `exit 1`.

### Step 3: Tests

- `tests/test_security_gate.py`: add `test_pip_audit_missing_report_fails` and `test_bandit_empty_report_fails` — call `main(["pip-audit", str(missing), "--severity", "HIGH", "--status", str(tmp_status)])` and assert the return is `1`. Add `test_gitleaks_missing_report_is_clean` asserting gitleaks still returns `0` for a missing report (lock in the intended asymmetry). Model after the existing tests in the file (they already use `tmp_path`).
- `tests/test_quality_gate.py` (create): point the validator at an empty `tmp_path` golden dir (monkeypatch `quality_gate.GOLDEN_DIR`) and assert `SystemExit` with code `1`.

**Verify:** `.venv/bin/pytest tests/test_security_gate.py tests/test_quality_gate.py -q` → all pass.

## Test plan

- New security-gate tests: missing pip-audit report → exit 1; empty bandit report → exit 1; missing gitleaks report → exit 0 (clean).
- New quality-gate test: empty golden dir → exit 1.
- Verification: `make test` → all pass.

## Done criteria

ALL must hold:

- [ ] `security_gate.py` raises/fails (non-zero) for a missing **or** empty pip-audit/bandit report; gitleaks empty still passes
- [ ] `quality_gate.py` exits 1 when no golden cases exist
- [ ] The `if os.getenv("OLLAMA_API_URL"): pass` no-op is replaced with a real fail/warn (no silent `pass`)
- [ ] New tests in `tests/test_security_gate.py` and `tests/test_quality_gate.py` cover these and pass
- [ ] `make test` exits 0; `make lint` exits 0
- [ ] Only the two scripts and their test files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- A scanner legitimately produces **no report file** on a clean run in this repo's CI (check `.github/workflows/ci.yml` around lines 180/209/232 and the Makefile `security`/`quality-ci` targets) — if so, the "missing = fail" rule for that tool needs adjustment; report what you found.
- `quality_gate.py` is intentionally run with `OLLAMA_API_URL` set somewhere — report it rather than hard-failing.
- The live code no longer matches the excerpts (drift).

## Maintenance notes

- A reviewer should confirm the asymmetry is intentional and documented in the tests: pip-audit/bandit missing-or-empty → fail; gitleaks empty → clean.
- Follow-up (deferred): consider validating the report's top-level shape (that a bandit report has a `results` key, a pip-audit report has `dependencies`) to catch "wrong file written to the path" as well — note for the owner; not required here.
