"""Regression tests for refinery source clone fallback behavior."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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


class _LockedError(Exception):
    winerror = 32


class _StubGitHandler:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def clone_repo(self, repo_url: str, target_dir: Path) -> None:
        raise self.exc


def test_safe_clone_uses_existing_repo_when_locked(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    (source_dir / ".git").mkdir(parents=True)

    handler = _StubGitHandler(_LockedError("locked"))

    resolved = refinery_main._safe_clone_source_repo(
        handler, "https://example.com/repo.git", source_dir
    )

    assert resolved == source_dir


def test_safe_clone_raises_when_no_repo_present(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    handler = _StubGitHandler(_LockedError("locked"))

    try:
        refinery_main._safe_clone_source_repo(
            handler, "https://example.com/repo.git", source_dir
        )
    except Exception as exc:
        assert isinstance(exc, _LockedError)
    else:
        raise AssertionError("Expected locked error to be raised when repo missing.")
