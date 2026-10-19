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

The `test-system` recipe in `Makefile` selects the S1 refactor, activity
monitor and bootstrap coverage tests. Use that target rather than copying
an incomplete pytest file list. The coverage configuration defines the
measured source set and threshold.

### Configuration Files

- **Test Config**: `tools/ci/pytest_system.toml`
- **Coverage Config**: `tools/ci/coverage_system.rc`

## Runtime-config isolation guard

The autouse `_restore_runtime_config_state` fixture in `tests/conftest.py`
snapshots the global runtime-config state (`RUNTIME` fields, `_CONFIG_STATE`,
`_CURRENT_SNAPSHOT`, `_CONFIG_VERSION`) before each test and restores it
afterwards. Without it, a test that publishes a runtime-config snapshot leaves
it behind for later tests: seeds `722672841` and `303127521` used to fail with
`min_content_length` falling back to 1000 and `KeyError: 'type'` in
`DatabaseManager._setup_database`. Reproduce order-dependent failures with
`pytest tests -p randomly --randomly-seed=N`. The guard is manual
save/restore on purpose — an autouse fixture must not depend on `monkeypatch`
(that changes the teardown order of every test).

## CI Integration

The `system-contract-and-coverage` job in `.github/workflows/system-verification.yml`
runs this gate automatically on PRs and pushes to `main` that affect system files
(`news_collector/system/**`, `tests/unit/system/**`, `tools/ci/**`).  It is intentionally
separate from the main `ci.yml` workflow to keep system verification scoped to changes
that affect the system layer.  See [`docs/ci.md`](ci.md) for the full workflow reference.
