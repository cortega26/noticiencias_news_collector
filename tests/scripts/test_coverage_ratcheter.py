from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

RATCHET = Path(__file__).resolve().parents[2] / "scripts" / "coverage_ratcheter.sh"

COVERAGE_XML = """<?xml version="1.0" ?>
<coverage version="7.13.2" lines-valid="100" lines-covered="74" line-rate="0.74"
          branches-valid="0" branches-covered="0" branch-rate="0">
  <packages>
    <package name="news_collector" line-rate="0.74" branch-rate="0">
      <classes>
        <class name="a.py" filename="news_collector/a.py" line-rate="0.9" branch-rate="0" complexity="0">
          <methods/>
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="1"/>
          </lines>
        </class>
        <class name="b.py" filename="news_collector/b.py" line-rate="0.0" branch-rate="0" complexity="0">
          <methods/>
          <lines>
            <line number="1" hits="0"/>
          </lines>
        </class>
        <class name="logger.py" filename="news_collector/utils/logger.py" line-rate="0.0" branch-rate="0" complexity="0">
          <methods/>
          <lines>
            <line number="1" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

BASELINE = json.dumps({"total_line": 74.0, "total_branch": 70.0}, sort_keys=True)

PYPROJECT_OMIT = """[tool.coverage.run]
omit = [
    "news_collector/utils/logger.py",
]
"""


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


def _make_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    for rel, content in (
        (".coverage-baseline", BASELINE),
        ("coverage.xml", COVERAGE_XML),
        ("pyproject.toml", PYPROJECT_OMIT),
        ("news_collector/a.py", "A = 1\n"),
        ("news_collector/b.py", "B = 1\n"),
        ("news_collector/deleted.py", "D = 1\n"),
        ("news_collector/utils/logger.py", "LOG = 1\n"),
    ):
        _write(tmp_path, rel, content)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "-q", "base")
    return tmp_path


def _run_check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RATCHET), "check", "--base-ref", "base"],
        cwd=root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "COVERAGE_XML": str(root / "coverage.xml"),
            "BASELINE_FILE": str(root / ".coverage-baseline"),
        },
    )


def test_check_ignores_deleted_files_in_diff(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _git(root, "rm", "-q", "news_collector/deleted.py")
    _git(root, "commit", "-q", "-m", "delete module")

    result = _run_check(root)

    assert result.returncode == 0, result.stderr


def test_check_skips_changed_files_omitted_in_pyproject(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write(root, "news_collector/utils/logger.py", "LOG = 2\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "touch omitted file")

    result = _run_check(root)

    assert result.returncode == 0, result.stderr


def test_check_fails_for_changed_file_below_threshold(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write(root, "news_collector/b.py", "B = 2\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "touch low coverage file")

    result = _run_check(root)

    assert result.returncode == 1
    assert "below 90%" in result.stderr


def test_check_detects_changed_root_level_module(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write(
        root,
        "coverage.xml",
        COVERAGE_XML.replace('hits="1"', 'hits="0"', 3),
    )
    _write(root, "news_collector/a.py", "A = 2\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "touch root level module")

    result = _run_check(root)

    assert result.returncode == 1
    assert "news_collector/a.py" in result.stderr


def test_check_without_changed_files_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    result = _run_check(root)

    assert result.returncode == 0, result.stderr
