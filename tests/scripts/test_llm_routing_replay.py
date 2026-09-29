from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPLAY = Path(__file__).resolve().parents[2] / "scripts" / "llm_routing_replay.py"

PHASES = (
    "dry-run",
    "generate",
    "judge",
    "cross-critic",
    "grounded",
    "bundle",
    "analyze",
)


def test_cli_help_lists_every_phase() -> None:
    """Guards the lost `def main` regression: argparse must be reachable."""
    result = subprocess.run(
        [sys.executable, str(REPLAY), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for phase in PHASES:
        assert phase in result.stdout


def test_cli_requires_a_phase() -> None:
    result = subprocess.run(
        [sys.executable, str(REPLAY)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--phase" in result.stderr
