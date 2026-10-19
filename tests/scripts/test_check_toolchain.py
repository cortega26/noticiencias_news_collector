"""Tests for scripts/check_toolchain.py (plan 144).

The gate reads `.pre-commit-config.yaml` and compares the pinned revisions
with the versions installed in the running interpreter, so the failure test
doctors a copy of the real config (a bogus ruff rev) instead of mocking the
metadata layer.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_toolchain.py"
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"


def run_check(config: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def test_returncode_and_table_for_repository_pins() -> None:
    result = run_check(CONFIG)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[toolchain] OK" in result.stdout
    assert "ruff" in result.stdout
    assert "pdoc" in result.stdout


def test_mismatched_pin_fails_and_names_the_tool(tmp_path: Path) -> None:
    text = CONFIG.read_text(encoding="utf-8")
    doctored = text.replace("rev: v0.14.14", "rev: v0.0.1")
    assert doctored != text
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(doctored, encoding="utf-8")

    result = run_check(config)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "MISMATCH" in result.stdout
    assert "ruff" in result.stdout
