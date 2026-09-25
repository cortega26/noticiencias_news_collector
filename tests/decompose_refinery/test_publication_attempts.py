"""
tests/decompose_refinery/test_publication_attempts.py

Verifies the publication-attempt artifact module (plan 060 Phase 7a).

Import path after implementation:
    from news_collector.logic.workflows.publication_attempts import (
        artifact_name,
        persist_interrupted_attempt,
        persist_publication_attempt,
        read_publication_attempt,
    )
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_collector.contracts import PublicationAttemptStageResult
from news_collector.logic.workflows.publication_attempts import (
    artifact_name,
    persist_interrupted_attempt,
    persist_publication_attempt,
    read_publication_attempt,
)


@pytest.fixture
def attempts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "publication_attempts"
    d.mkdir()
    return d


def _stages() -> list[PublicationAttemptStageResult]:
    return [
        PublicationAttemptStageResult(name="identity_resolved", success=True),
        PublicationAttemptStageResult(
            name="file_written", success=True, details={"output_filename": "x.md"}
        ),
    ]


# ---------------------------------------------------------------------------
# artifact_name
# ---------------------------------------------------------------------------


class TestArtifactName:
    def test_plain_id_is_preserved(self):
        assert artifact_name("42") == "42"

    def test_unsafe_characters_are_replaced(self):
        safe = artifact_name("á_b$c")
        assert safe != "á_b$c"
        assert "/" not in safe and "$" not in safe

    def test_empty_or_symbol_only_id_falls_back_to_unknown(self):
        assert artifact_name("") == "unknown"
        assert artifact_name("$$$") == "unknown"


# ---------------------------------------------------------------------------
# persist_publication_attempt / read_publication_attempt round-trip
# ---------------------------------------------------------------------------


class TestPersistAndRead:
    def test_full_summary_round_trips(self, attempts_dir: Path):
        path = persist_publication_attempt(
            attempts_dir,
            article_id="42",
            success=True,
            stages=_stages(),
            target_repo="https://github.com/org/repo",
            output_filename="2024-01-25-test.md",
            final_slug="2024-01-25-test",
            branch_name="content/update-2024-01-25-test",
            pr_url="https://github.com/org/repo/pull/1",
            validation_summary_path="/tmp/42.frontend_validation.json",
        )

        assert path == attempts_dir / "42.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["article_id"] == "42"
        assert data["success"] is True
        assert data["pr_url"] == "https://github.com/org/repo/pull/1"
        assert data["branch_name"] == "content/update-2024-01-25-test"
        assert data["final_slug"] == "2024-01-25-test"
        assert data["output_filename"] == "2024-01-25-test.md"
        assert data["validation_summary_path"] == "/tmp/42.frontend_validation.json"
        assert data["target_repo"] == "https://github.com/org/repo"
        assert [s["name"] for s in data["stages"]] == [
            "identity_resolved",
            "file_written",
        ]

        assert read_publication_attempt(attempts_dir, "42") == data

    def test_failure_class_is_persisted(self, attempts_dir: Path):
        persist_publication_attempt(
            attempts_dir,
            article_id="7",
            success=False,
            stages=_stages(),
            failure_class="frontend_build_failure",
        )
        data = read_publication_attempt(attempts_dir, "7")
        assert data is not None
        assert data["success"] is False
        assert data["failure_class"] == "frontend_build_failure"

    def test_unsafe_article_id_uses_sanitized_filename(self, attempts_dir: Path):
        path = persist_publication_attempt(
            attempts_dir, article_id="á_b$c", success=True, stages=[]
        )
        assert path.name == f"{artifact_name('á_b$c')}.json"
        assert read_publication_attempt(attempts_dir, "á_b$c") is not None

    def test_read_missing_returns_none(self, attempts_dir: Path):
        assert read_publication_attempt(attempts_dir, "nope") is None

    def test_read_corrupt_json_returns_none(self, attempts_dir: Path):
        (attempts_dir / "9.json").write_text("{not json", encoding="utf-8")
        assert read_publication_attempt(attempts_dir, "9") is None


# ---------------------------------------------------------------------------
# persist_interrupted_attempt
# ---------------------------------------------------------------------------


class TestPersistInterrupted:
    def test_writes_failed_summary_when_absent(self, attempts_dir: Path):
        persist_interrupted_attempt(attempts_dir, "42", _stages())
        data = read_publication_attempt(attempts_dir, "42")
        assert data is not None
        assert data["success"] is False
        # Literal contract has no generic failure class; must stay unset.
        assert data["failure_class"] is None

    def test_never_overwrites_a_prior_success(self, attempts_dir: Path):
        persist_publication_attempt(
            attempts_dir, article_id="42", success=True, stages=_stages()
        )
        persist_interrupted_attempt(attempts_dir, "42", _stages())
        data = read_publication_attempt(attempts_dir, "42")
        assert data is not None
        assert data["success"] is True

    def test_noop_for_unknown_id_or_empty_stages(self, attempts_dir: Path):
        persist_interrupted_attempt(attempts_dir, "unknown", _stages())
        persist_interrupted_attempt(attempts_dir, "", _stages())
        persist_interrupted_attempt(attempts_dir, "42", [])
        persist_interrupted_attempt(attempts_dir, "42", None)
        assert list(attempts_dir.glob("*.json")) == []
