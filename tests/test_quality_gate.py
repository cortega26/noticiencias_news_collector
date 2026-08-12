"""Tests for the snapshot quality gate."""

from pathlib import Path

import pytest

from scripts import quality_gate


def test_empty_golden_directory_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 1


def test_ollama_configuration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "case").mkdir()
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)
    monkeypatch.setenv("OLLAMA_API_URL", "http://localhost:11434")

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 1
