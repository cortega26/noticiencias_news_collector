"""Plan 086: PROrchestrator.create_pr fails closed on non-numeric article ids.

A title-fallback (non-DB) identity must never produce a real GitHub PR that
no ``publishing`` row or webhook callback can correlate with. These tests pin:

1. non-numeric id -> explicit error, ``create_pull_request`` never called.
2. numeric id     -> PR created and ``mark_article_published`` called
   (guards the fix against over-correction of the happy path).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from news_collector.logic.workflows.pr_orchestrator import PROrchestrator


class FakeGit:
    """Records create_pull_request calls instead of touching GitHub."""

    def __init__(self, pr_url: str | None = "https://example.test/pr/1"):
        self.calls: list[dict] = []
        self.pr_url = pr_url

    def create_pull_request(self, **kwargs) -> str | None:
        self.calls.append(kwargs)
        return self.pr_url


class FakeDB:
    """Records mark_article_published calls instead of touching the DB."""

    def __init__(self):
        self.marks: list[tuple] = []

    def mark_article_published(self, numeric_id, pr_url, refinery_id):
        self.marks.append((numeric_id, pr_url, refinery_id))


def _orchestrator(git, db) -> PROrchestrator:
    config = SimpleNamespace(
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
    )
    return PROrchestrator(git=git, db=db, config=config)


def _article() -> dict:
    return {
        "title": "Some Title",
        "source_id": "src",
        "source_name": "Test Source",
    }


def test_create_pr_rejects_non_numeric_id_without_side_effect():
    """Non-numeric (title-fallback) id -> error, no PR call, no DB mark."""
    git, db = FakeGit(), FakeDB()
    orchestrator = _orchestrator(git, db)

    with pytest.raises(AttributeError, match="not a numeric DB id"):
        orchestrator.create_pr(
            article_id="Some Title",
            article=_article(),
            branch_name="content/update-some-title",
            output_filename="some-title.md",
        )

    assert git.calls == []
    assert db.marks == []


def test_create_pr_accepts_numeric_id_and_marks_published():
    """Numeric id -> PR created and DB mark called (happy path preserved)."""
    git, db = FakeGit(), FakeDB()
    orchestrator = _orchestrator(git, db)

    result = orchestrator.create_pr(
        article_id="123",
        article=_article(),
        branch_name="content/update-123",
        output_filename="123.md",
    )

    assert result.pr_url == "https://example.test/pr/1"
    assert len(git.calls) == 1
    assert db.marks == [(123, "https://example.test/pr/1", "123")]


def test_review_notes_are_appended_to_the_pr_body_only_when_given():
    git, db = FakeGit(), FakeDB()
    orchestrator = _orchestrator(git, db)
    kwargs = dict(
        article_id="12", article=_article(), branch_name="b", output_filename="x.md"
    )
    orchestrator.create_pr(**kwargs)
    orchestrator.create_pr(**kwargs, review_notes="  ## Revisar\n- algo  ")
    plain, noted = (c["body"] for c in git.calls)
    assert "Revisar" not in plain
    assert noted.endswith("## Revisar\n- algo")
    assert noted.startswith(plain)
