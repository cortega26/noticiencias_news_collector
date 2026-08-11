"""Tests for scripts/validate_plans_ledger.py fail-closed semantics.

Each test builds an isolated git repo with a plans/README.md ledger plus plan
files, runs the validator as a subprocess, and asserts on exit code/output.
The ledger table mirrors the real plans/README.md 6-column shape.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).resolve().parents[2] / "scripts" / "validate_plans_ledger.py"

TABLE_HEADER = """\
| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
"""


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def real_hash(root: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def write_ledger(root: Path, rows: list[str], stamp: str | None = None) -> None:
    stamp = stamp or real_hash(root)
    table = "".join(f"| {row} |\n" for row in rows)
    (root / "plans" / "README.md").write_text(
        f"# Implementation Plans\n\n"
        f"**Last verified:** `{stamp}` (2026-08-11)\n\n"
        f"{TABLE_HEADER}{table}",
        encoding="utf-8",
    )


@pytest.fixture()
def ledger_repo(tmp_path: Path) -> Path:
    """Git repo with an initial commit; ledger written per-test via write_ledger."""
    root = tmp_path / "repo"
    plans = root / "plans"
    archive = plans / "archive"
    archive.mkdir(parents=True)
    (archive / "001-first-plan.md").write_text("done", encoding="utf-8")
    (plans / "README.md").write_text("placeholder", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "ledger"], check=True)
    return root


def test_clean_ledger_passes(ledger_repo: Path) -> None:
    write_ledger(ledger_repo, [])
    result = run_validator(ledger_repo)
    assert result.returncode == 0, result.stdout
    assert "OK" in result.stdout


def test_done_plan_in_root_fails(ledger_repo: Path) -> None:
    (ledger_repo / "plans" / "002-done-plan.md").write_text("done", encoding="utf-8")
    write_ledger(
        ledger_repo, ["002 | [Done plan](002-done-plan.md) | P1 | S | — | DONE"]
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "still in plans/ root" in result.stdout


def test_done_plan_kept_with_reason_passes(ledger_repo: Path) -> None:
    (ledger_repo / "plans" / "002-done-plan.md").write_text("done", encoding="utf-8")
    write_ledger(
        ledger_repo,
        [
            "002 | [Done plan](002-done-plan.md) | P1 | S | — | DONE — KEEP: operator review"
        ],
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 0, result.stdout


def test_missing_last_verified_stamp_fails(ledger_repo: Path) -> None:
    (ledger_repo / "plans" / "README.md").write_text(
        "# Implementation Plans\n\nNo stamp here.\n",
        encoding="utf-8",
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "Last verified" in result.stdout


def test_stale_stamp_commit_fails(ledger_repo: Path) -> None:
    write_ledger(ledger_repo, [], stamp="deadbeef")
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "`deadbeef`" in result.stdout


def test_bogus_cited_commit_fails(ledger_repo: Path) -> None:
    write_ledger(ledger_repo, [])
    (ledger_repo / "plans" / "README.md").write_text(
        (ledger_repo / "plans" / "README.md").read_text(encoding="utf-8")
        + "\nSee commit `deadbeef` for details.\n",
        encoding="utf-8",
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "`deadbeef`" in result.stdout


def test_unknown_status_fails(ledger_repo: Path) -> None:
    (ledger_repo / "plans" / "002-done-plan.md").write_text("done", encoding="utf-8")
    write_ledger(
        ledger_repo, ["002 | [Done plan](002-done-plan.md) | P1 | S | — | SOMETIMES"]
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "unknown status" in result.stdout


def test_orphan_plan_file_fails(ledger_repo: Path) -> None:
    write_ledger(ledger_repo, [])
    (ledger_repo / "plans" / "002-untracked-plan.md").write_text(
        "done", encoding="utf-8"
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "has no row" in result.stdout


def test_row_without_plan_file_fails(ledger_repo: Path) -> None:
    write_ledger(
        ledger_repo,
        ["002 | [Missing plan](002-missing-plan.md) | P1 | S | — | PARTIAL"],
    )
    result = run_validator(ledger_repo)
    assert result.returncode == 1
    assert "no plan file/folder is present" in result.stdout
