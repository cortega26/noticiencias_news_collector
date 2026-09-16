"""Tests for the snapshot quality gate."""

import json
from pathlib import Path

import pytest

from scripts import quality_gate

INPUT_TEXT = (
    "Biologists exploring the dense cloud forests of the Andes have identified "
    "a remarkable new species of frog that does not croak. The team plans to "
    "return next year to study mating rituals and assess population size. "
) * 2

CONTENT_TEXT = (
    '---\ntitle: "Silent frog discovered in a remote Andean valley"\n---\n\n'
    "Scientists found a remarkable new frog species in the Andean cloud forest "
    "that communicates through visual signaling instead of croaking. "
    "The expedition spent three weeks in a remote valley documenting hand-waving "
    "behavior known as foot-flagging. Genetic analysis confirms the lineage "
    "diverged about two million years ago from its closest relatives. "
    "Conservationists urge immediate protection of the valley, which faces "
    "pressure from illegal logging operations that threaten this unique amphibian "
    "and its fragile habitat for future study."
)

EXPECTATIONS = {
    "must_have_sections": ["foot-flagging"],
    "forbidden_phrases": ["eslabón perdido"],
    "must_not_claim": ["primera rana del mundo"],
    "headlines_schema": ["directo", "pregunta", "relevancia"],
    "min_length_chars": 500,
    "max_length_ratio": 2.5,
}


def _write_valid_case(case_dir: Path) -> None:
    """Write a minimal valid golden case (mirrors quality_gate/golden/01_frog/)."""
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "input.txt").write_text(INPUT_TEXT)
    (case_dir / "expected.json").write_text(json.dumps(EXPECTATIONS))
    (case_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "_meta": {
                    "generated_by": "quality_gate_refresh",
                    "git_commit": "test-commit",
                },
                "content": CONTENT_TEXT,
                "headlines": {
                    "directo": "Silent frog discovered in a remote Andean valley",
                    "pregunta": "How do frogs communicate without croaking?",
                    "relevancia": "Protecting the valley preserves a unique lineage.",
                },
            }
        )
    )


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


def test_valid_golden_directory_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_valid_case(tmp_path / "case01")
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)
    monkeypatch.delenv("OLLAMA_API_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 0


def test_tampered_snapshot_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case_dir = tmp_path / "case01"
    _write_valid_case(case_dir)
    # Tamper exactly one compared byte inside the required-section token.
    snapshot_path = case_dir / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["content"] = snapshot["content"].replace("foot-flagging", "foot-flaxging")
    snapshot_path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(quality_gate, "GOLDEN_DIR", tmp_path)
    monkeypatch.delenv("OLLAMA_API_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        quality_gate.QualityGateValidator().run()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Missing required section content" in out
