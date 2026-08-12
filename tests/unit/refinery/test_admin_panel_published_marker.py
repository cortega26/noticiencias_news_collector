"""Tests for the Refinery UI 'already published' detection (2026-08-12).

The DB-only check (is_article_in_flight_or_done) cannot see articles
published from exports whose refinery_id is the title (non-numeric). The
UI now also resolves the target repo's published content snapshot and
flags/hides those articles so re-selecting them cannot silently re-run
the pipeline and create a duplicate PR.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.refinery import admin_panel


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
        "apps.refinery.admin_panel.resolve_published_content_snapshot",
        return_value=snapshot,
    ):
        result = admin_panel._resolve_published_refinery_ids(
            target_repo_url="https://github.com/org/repo.git",
            github_token="token",
            temp_target_dir=tmp_path,
        )

    assert "123" in result
    assert "AI Safety Regulations in the U.S. Could Give Hackers an Edge" in result
    assert len(result) == 2  # None refinery_id excluded


def test_resolve_published_refinery_ids_empty_without_target_url():
    result = admin_panel._resolve_published_refinery_ids(
        target_repo_url="",
        github_token="token",
        temp_target_dir=Path("/nonexistent"),
    )
    assert result == set()


def test_resolve_published_refinery_ids_best_effort_on_error(tmp_path: Path):
    with patch(
        "apps.refinery.admin_panel.resolve_published_content_snapshot",
        side_effect=RuntimeError("clone failed"),
    ):
        result = admin_panel._resolve_published_refinery_ids(
            target_repo_url="https://github.com/org/repo.git",
            github_token="token",
            temp_target_dir=tmp_path,
        )
    assert result == set()
