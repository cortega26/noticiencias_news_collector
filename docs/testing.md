# System Verification & Governance

## Overview

We maintain a strict verification gate for the core system architecture (S1 / S1-C refactors). This ensures that critical system components (`bootstrap.py`, `pipeline.py`) remain robust and decoupled from legacy debt.

## Acceptance Criteria

Any change to `news_collector/system/` must pass the **System Verification Gate**:

1.  **Regression Tests**: All tests in `tests/unit/system/test_s1_refactor.py` must pass.
2.  **Scoped Coverage**: New modules (`bootstrap.py`, `pipeline.py`) must maintain **≥ 80% code coverage**.
3.  **Legacy Exclusion**: Coverage explicitly excludes `news_collector/system/__init__.py`.

## Running Verification

To run the verification suite locally (identical to CI):

```bash
make test-system
```

This command executes:

```bash
pytest -c tools/ci/pytest_system.toml --cov-config=tools/ci/coverage_system.rc tests/unit/system/test_s1_refactor.py
```

### Configuration Files

- **Test Config**: `tools/ci/pytest_system.toml`
- **Coverage Config**: `tools/ci/coverage_system.rc`

## CI Integration

The `system-contract-and-coverage` job in GitHub Actions runs this gate automatically on PRs affecting system files.
