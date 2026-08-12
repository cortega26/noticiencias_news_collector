"""Tests for the 'already published' refinery_id resolution (2026-08-12).

The DB-only published check (is_article_in_flight_or_done) cannot see
articles published from exports whose refinery_id is the title
(non-numeric). resolve_published_refinery_ids() resolves the target repo's
published-content snapshot (manifest + frontmatter) so the Refinery UI can
flag/hide those articles instead of silently re-running the pipeline and
creating a duplicate PR.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from apps.refinery import published_content


class _FakeArticle:
    def __init__(self, refinery_id: str | None):
        self.refinery_id = refinery_id


class _FakeSnapshot:
    def __init__(self, articles):
        self.articles = articles


def test_resolve_published_refinery_ids_returns_manifest_ids(tmp_path: Path):
    snapshot = _FakeSnapshot(
        [
            _FakeArticle("123"),
            _FakeArticle(
                "AI Safety Regulations in the U.S. Could Give Hackers an Edge"
            ),
            _FakeArticle(None),
        ]
    )

    with patch(
        "apps.refinery.published_content.resolve_published_content_snapshot",
        return_value=snapshot,
    ):
        result = published_content.resolve_published_refinery_ids(
            target_repo_url="https://github.com/org/repo.git",
            collector_repo_root=tmp_path,
            temp_target_dir=tmp_path,
            github_token="token",
        )

    assert "123" in result
    assert "AI Safety Regulations in the U.S. Could Give Hackers an Edge" in result
    assert len(result) == 2  # None refinery_id excluded


def test_resolve_published_refinery_ids_empty_without_target_url(tmp_path: Path):
    result = published_content.resolve_published_refinery_ids(
        target_repo_url="",
        collector_repo_root=tmp_path,
        temp_target_dir=tmp_path,
        github_token="token",
    )
    assert result == set()


def test_resolve_published_refinery_ids_best_effort_on_error(tmp_path: Path):
    with patch(
        "apps.refinery.published_content.resolve_published_content_snapshot",
        side_effect=RuntimeError("clone failed"),
    ):
        result = published_content.resolve_published_refinery_ids(
            target_repo_url="https://github.com/org/repo.git",
            collector_repo_root=tmp_path,
            temp_target_dir=tmp_path,
            github_token="token",
        )
    assert result == set()
