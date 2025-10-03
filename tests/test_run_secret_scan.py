"""Tests for the secret scan helper CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import run_secret_scan


def test_severity_choice_validates_options() -> None:
    assert run_secret_scan._severity_choice("low") == "LOW"
    assert run_secret_scan._severity_choice("CRITICAL") == "CRITICAL"
    with pytest.raises(argparse.ArgumentTypeError):
        run_secret_scan._severity_choice("unknown")


def test_ensure_directory_requires_existing_directory(tmp_path: Path) -> None:
    resolved = run_secret_scan._ensure_directory(tmp_path)
    assert resolved == tmp_path.resolve()

    file_path = tmp_path / "file.txt"
    file_path.write_text("secret", encoding="utf-8")
    with pytest.raises(argparse.ArgumentTypeError):
        run_secret_scan._ensure_directory(file_path)

    missing = tmp_path / "missing"
    with pytest.raises(argparse.ArgumentTypeError):
        run_secret_scan._ensure_directory(missing)


def test_build_command_serializes_arguments(tmp_path: Path) -> None:
    command = run_secret_scan.build_command(
        python_bin=Path("/usr/bin/python3"),
        output=tmp_path / "report.json",
        severity="HIGH",
        target=tmp_path,
    )

    assert command[0] == "/usr/bin/python3"
    assert command[1:4] == ["-m", "trufflehog3", "--format"]
    assert "--no-history" in command
    assert str(tmp_path) in command
