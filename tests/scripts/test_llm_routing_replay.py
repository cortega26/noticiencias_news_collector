from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import llm_routing_replay
from scripts.llm_routing_replay import (
    _case_input,
    _load_completed_cross_critic_keys,
)

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


def test_cross_critic_resume_retries_unreviewed_and_failed_rows(tmp_path: Path) -> None:
    path = tmp_path / "cross_critic.jsonl"

    def verdict(approved: bool, score: int) -> dict:
        scores = {
            "hook_score": score,
            "clarity_score": score,
            "structure_score": score,
            "rigor_score": score,
            "voice_score": score,
            "shareability_score": score,
            "closing_score": score,
        }
        return {"approved": approved, "average": float(score), "scores": scores}

    records = [
        {
            "db_id": "1",
            "output_arm": "A",
            "critic_arm": "A",
            "status": "unreviewed",
            "approved": None,
        },
        {
            "db_id": "2",
            "output_arm": "A",
            "critic_arm": "B",
            "status": "failed",
            "approved": None,
        },
        {
            "db_id": "3",
            "output_arm": "A",
            "critic_arm": "C",
            "status": "ok",
            "approved": False,
            "verdict": verdict(False, 6),
        },
        {
            "db_id": "4",
            "output_arm": "B",
            "critic_arm": "A",
            "status": "ok",
            "approved": True,
            "verdict": None,
        },
        {
            "db_id": "5",
            "output_arm": "B",
            "critic_arm": "B",
            "status": "ok",
            "approved": True,
            "verdict": verdict(True, 7),
        },
        {
            "db_id": "6",
            "output_arm": "B",
            "critic_arm": "C",
            "status": "ok",
            "approved": False,
            "verdict": verdict(False, 7),
        },
        {"status": "ok", "approved": True, "verdict": verdict(True, 7)},
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\nnot-json\n",
        encoding="utf-8",
    )

    assert _load_completed_cross_critic_keys(path) == {
        ("3", "A", "C"),
        ("5", "B", "B"),
    }


@pytest.mark.parametrize(
    ("stored_mode", "expected_mode"),
    (("full_text", "summary_fallback"), ("summary_only", "summary_only")),
)
def test_case_input_preserves_actual_source_completeness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stored_mode: str,
    expected_mode: str,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "news_v3.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE articles (id INTEGER, title TEXT, summary TEXT, content TEXT, "
            "content_mode TEXT, url TEXT, source_id TEXT, source_name TEXT, category TEXT)"
        )
        db.execute(
            "INSERT INTO articles VALUES (1, 'Title', 'RSS excerpt', '', ?, "
            "'https://example.com', 'source-1', 'Example', 'ciencia')",
            (stored_mode,),
        )
    monkeypatch.setattr(llm_routing_replay, "REPO_ROOT", tmp_path)

    result = _case_input("1")

    assert result["content"] == "RSS excerpt"
    assert result["content_mode"] == expected_mode
