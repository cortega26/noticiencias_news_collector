"""Regression tests for repository-local virtualenv portability."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_local_virtualenv_is_ignored_and_not_tracked() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".venv/" in gitignore
    assert ".venv-refinery/" in gitignore

    tracked = subprocess.run(
        ["git", "ls-files", ".venv", ".venv-refinery"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout.strip() == ""


def test_bootstrap_rejects_missing_base_interpreter() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "os.path.exists(sys._base_executable)" in makefile
