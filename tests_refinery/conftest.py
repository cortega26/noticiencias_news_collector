"""Shared fixtures for AppTest-based Refinery characterization tests.

Runs only under the isolated `.venv-refinery` environment (`make
test-refinery`) — the main `.venv` has no `streamlit` installed at all, so
this directory is deliberately outside `testpaths=["tests"]` in the main
`pyproject.toml` and is never collected by `make test`/`make test-all`.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from news_collector.logic.workflows import published_content

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_PANEL_PATH = REPO_ROOT / "apps" / "refinery" / "admin_panel.py"


@pytest.fixture(autouse=True)
def _refinery_test_env(monkeypatch):
    """Bypass the UI auth gate (the app's own documented dev/test escape
    hatch, not a workaround) and point the app at the real repo root, same
    as `make refinery`/`make test-refinery` set at the process level."""
    monkeypatch.setenv("REFINERY_UI_UNSAFE_ALLOW", "1")
    monkeypatch.setenv("NEWS_COLLECTOR_PATH", str(REPO_ROOT))
    # These tests exercise widgets/cache behavior, not checkout discovery.
    # Never inspect sibling directories outside the fixture workspace (e.g.
    # protected systemd directories when this checkout lives under /tmp).
    monkeypatch.setattr(
        published_content,
        "iter_candidate_repo_roots",
        lambda *_args, **_kwargs: [REPO_ROOT],
    )
    # Nor clone the target repo: the panel reads TARGET_REPO_URL only from the
    # untracked `.env`, so without it the real resolver runs `git clone ''`.
    # An empty snapshot keeps the published-content tab inert and hermetic.
    monkeypatch.setattr(
        published_content,
        "resolve_published_content_snapshot",
        lambda **_kwargs: SimpleNamespace(
            articles=[], repo_root=REPO_ROOT, source_label="Fixture vacío"
        ),
    )
    os.chdir(REPO_ROOT)
    yield
