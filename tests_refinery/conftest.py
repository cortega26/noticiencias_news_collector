"""Shared fixtures for AppTest-based Refinery characterization tests.

Runs only under the isolated `.venv-refinery` environment (`make
test-refinery`) — the main `.venv` has no `streamlit` installed at all, so
this directory is deliberately outside `testpaths=["tests"]` in the main
`pyproject.toml` and is never collected by `make test`/`make test-all`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_PANEL_PATH = REPO_ROOT / "apps" / "refinery" / "admin_panel.py"


@pytest.fixture(autouse=True)
def _refinery_test_env(monkeypatch):
    """Bypass the UI auth gate (the app's own documented dev/test escape
    hatch, not a workaround) and point the app at the real repo root, same
    as `make refinery`/`make test-refinery` set at the process level."""
    monkeypatch.setenv("REFINERY_UI_UNSAFE_ALLOW", "1")
    monkeypatch.setenv("NEWS_COLLECTOR_PATH", str(REPO_ROOT))
    os.chdir(REPO_ROOT)
    yield
