"""End-to-end checks for refinery export selection fallback behavior."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Iterable


ROOT = Path(__file__).resolve().parents[2]
REFINERY_DIR = ROOT / "apps" / "refinery"
spec = importlib.util.spec_from_file_location(
    "refinery_main", REFINERY_DIR / "main.py"
)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load refinery main module for tests.")
if str(REFINERY_DIR) not in sys.path:
    sys.path.insert(0, str(REFINERY_DIR))
if "git" not in sys.modules:
    stub_git = types.ModuleType("git")
    stub_git.Repo = type(
        "Repo",
        (),
        {"clone_from": staticmethod(lambda *args, **kwargs: None)},
    )
    sys.modules["git"] = stub_git
refinery_main = importlib.util.module_from_spec(spec)
sys.modules["refinery_main"] = refinery_main
spec.loader.exec_module(refinery_main)


class _StubDB:
    def __init__(self, processed: Iterable[str] | None = None) -> None:
        self._processed = {str(item) for item in (processed or [])}

    def is_processed(self, filename: str) -> bool:
        return str(filename) in self._processed


def _write_export(path: Path, entries: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(entries)), encoding="utf-8")


def test_export_falls_back_when_cloud_empty(tmp_path: Path) -> None:
    cloned = tmp_path / "cloud" / "latest_articles.json"
    sibling = tmp_path / "local" / "latest_articles.json"

    _write_export(cloned, [])
    _write_export(sibling, [{"id": "42", "title": "Local Article"}])

    articles, selected = refinery_main._select_export_articles(
        cloned, sibling, _StubDB(), process_id=None
    )

    assert selected == sibling
    assert len(articles) == 1
    assert articles[0]["id"] == "42"


def test_export_falls_back_when_process_id_missing(tmp_path: Path) -> None:
    cloned = tmp_path / "cloud" / "latest_articles.json"
    sibling = tmp_path / "local" / "latest_articles.json"

    _write_export(cloned, [{"id": "A1", "title": "Cloud Article"}])
    _write_export(sibling, [{"id": "B2", "title": "Local Article"}])

    articles, selected = refinery_main._select_export_articles(
        cloned, sibling, _StubDB(), process_id="B2"
    )

    assert selected == sibling
    assert len(articles) == 1
    assert articles[0]["id"] == "B2"


def test_export_uses_preferred_when_match(tmp_path: Path) -> None:
    preferred = tmp_path / "preferred" / "latest_articles.json"
    cloned = tmp_path / "cloud" / "latest_articles.json"
    sibling = tmp_path / "local" / "latest_articles.json"

    _write_export(preferred, [{"id": "P1", "title": "Preferred Article"}])
    _write_export(cloned, [{"id": "C1", "title": "Cloud Article"}])
    _write_export(sibling, [{"id": "S1", "title": "Sibling Article"}])

    articles, selected = refinery_main._select_export_articles(
        cloned,
        sibling,
        _StubDB(),
        process_id="P1",
        preferred_path=preferred,
    )

    assert selected == preferred
    assert len(articles) == 1
    assert articles[0]["id"] == "P1"


def test_export_prefers_cloud_when_match(tmp_path: Path) -> None:
    cloned = tmp_path / "cloud" / "latest_articles.json"
    sibling = tmp_path / "local" / "latest_articles.json"

    _write_export(cloned, [{"id": "A1", "title": "Cloud Article"}])
    _write_export(sibling, [{"id": "B2", "title": "Local Article"}])

    articles, selected = refinery_main._select_export_articles(
        cloned, sibling, _StubDB(), process_id="A1"
    )

    assert selected == cloned
    assert len(articles) == 1
    assert articles[0]["id"] == "A1"


def test_export_returns_empty_when_no_candidates(tmp_path: Path) -> None:
    cloned = tmp_path / "cloud" / "latest_articles.json"
    sibling = tmp_path / "local" / "latest_articles.json"

    _write_export(cloned, [])
    _write_export(sibling, [])

    articles, selected = refinery_main._select_export_articles(
        cloned, sibling, _StubDB(), process_id=None
    )

    assert selected == cloned
    assert articles == []
