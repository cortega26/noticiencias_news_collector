# Quality Baseline & Phased Adoption Plan

## Initial Baseline (Run 1)

**Date:** 2026-01-24
**Total Bloating Issues:** ~164 (Ruff)
**Blockers:** Ruff strict mode prevents running subsequent tools (Mypy, Bandit, Semgrep) until resolved.

### Top Findings (Ruff)

1.  **Imports (I001)**: Widespread unorganized imports. Fixable automatically.
2.  **Complexity (C901)**: Several functions exceed complexity threshold (10).
    - `tools/placeholder_audit.py`: `run_audit`, `parse_diff`
    - `tools/scan_placeholders.py`: `run_scan`, `write_markdown`
    - `tools/diagnose_feeds.py`: `check_feed`
3.  **Simplicity (SIM)**: Nested `with` statements (`SIM117`), nested `if` (`SIM102`), duplicate `if` strings (`SIM114`).
4.  **Security/Best Practice (S)**:
    - `S603`/`S607`: `subprocess` calls in tooling scripts (audited, acceptable for internal tools but flagged).

## Adoption Strategy

### Phase 1: Clean Basics (Immediate)

- **Action**: Run `make quality-fix`.
- **Goal**: Eliminate I001, SIM\* auto-fixable issues.
- **Expectation**: Drop issue count from 164 -> ~100 or less.

### Phase 2: Complexity & Manual Fixes

- **Action**: Review `C901` violations.
- **Decision**:
  - Refactor `placeholder_audit.py` if frequent churn area.
  - Or add `# noqa: C901` if legacy/stable code.

### Phase 3: Strict Typing & Security (Next Gates)

- Once Ruff passes, Mypy and Bandit/Semgrep will become the active gates.
- **Mypy**: Likely to report `Any` usage or missing stubs.
- **Semgrep**: Will catch potential hardcoded secrets or risky patterns.

## Recommended Immediate Command

```bash
make quality-fix
```

Then run `make quality` again to see the next layer of issues.
