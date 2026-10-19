"""Tests for scripts/check_lock_parity.py (plan 144).

The gate compares `requirements.lock` with the running environment, so the
failure test points it at a doctored copy of the real lock (one runtime pin
moved) instead of mutating the venv.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_lock_parity.py"
LOCK = REPO_ROOT / "requirements.lock"


def run_check(lock: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--lock", str(lock)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def test_repository_lock_matches_installed_environment() -> None:
    result = run_check(LOCK)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[lock-parity] OK" in result.stdout


def test_version_drift_fails_and_names_the_package(tmp_path: Path) -> None:
    text = LOCK.read_text(encoding="utf-8")
    doctored = text.replace("alembic==1.20.0", "alembic==0.0.1", 1)
    assert doctored != text
    lock = tmp_path / "requirements.lock"
    lock.write_text(doctored, encoding="utf-8")

    result = run_check(lock)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "alembic" in result.stdout
    assert "version mismatch" in result.stdout
