# Spec: Fix Deprecated Streamlit use_container_width parameter

## Goals
- Replace all instances of deprecated `use_container_width` with the modern Streamlit `width` parameter.
- Keep the system free from deprecation warnings and future-proof.
- Add an automated regression check to prevent `use_container_width` from being reintroduced.

## Implementation Details

### 1. Streamlit UI Updates
- In `apps/refinery/admin_panel.py`, replace all occurrences of `use_container_width=True` with `width="stretch"`.

### 2. Regression Protection
- Add an automated regression test in `tests/test_ui_contracts.py` that reads `apps/refinery/admin_panel.py` and asserts that the string `"use_container_width"` is not present.
- Update `docs/AGENTS.md` under the `apps/refinery/` section to explicitly forbid the use of deprecated Streamlit arguments like `use_container_width`.

## Verification

### Automated Tests
- Run `make lint` (which runs `check-deprecated`).
- Run `make test` to execute the unit and contract tests.
