from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.logic.workflows.refinery_engine import RefineryEngine


def _make_engine():
    with patch(
        "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
    ) as MockAuditorClass:
        mock_config = MagicMock()
        mock_config.app.policy_integrity_mode = "disabled"
        mock_config.app.editorial_mode = "standard"
        mock_config.github = SimpleNamespace(
            target_repo_url="https://github.com/org/repo"
        )
        engine = RefineryEngine(MagicMock(), MagicMock(), MagicMock(), mock_config)
        engine.auditor = MockAuditorClass.return_value
        return engine


def test_extract_slug_sanitization():
    engine = _make_engine()
    test_cases = [
        ("slug: ../../../etc/passwd", "etc-passwd"),
        ("slug: ..\\\\..\\\\secret", "secret"),
        ("slug: %2e%2e/forbidden", "2e-2e-forbidden"),
        ("slug: a/../../b", "a-b"),
        ("slug: ¡weird-çhars!", "weird-chars"),
        ("slug: \x00null-byte", "null-byte"),
        ("slug: ---repeated---dashes---", "repeated-dashes"),
    ]
    for content, expected in test_cases:
        assert engine._extract_slug(content, "fallback") == expected


def test_extract_slug_empty_uses_fallback():
    engine = _make_engine()
    assert engine._extract_slug("slug: !@#$%^&*()", "fallback") == "article-fallback"


def test_slug_collision_handled(tmp_path):
    engine = _make_engine()
    engine.db.get_canonical_slug.return_value = None
    engine.db.get_publishing_state.return_value = None  # B-01: No publishing recovery
    engine.git = MagicMock()
    engine.git.create_branch.return_value = "content/update/test"
    engine.git.create_pull_request.return_value = "https://github.com/org/repo/pull/1"
    engine.editor = MagicMock()
    engine.editor.process_article.return_value = "content"
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 10.0}
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False

    article1 = {
        "id": "1",
        "title": "A long collision test title",
        "published_date": datetime(2024, 1, 1),
        "url": "http://example.com",
        "image_url": "https://example.com/image-1.png",
        "category": "sci",
        "source_id": "src",
        "source_name": "src",
        "source_metadata": {},
        "summary": "this is a long summary for test validation",
    }
    article2 = {
        "id": "2",
        "title": "Another long collision title",
        "published_date": datetime(2024, 1, 1),
        "url": "http://example.com/2",
        "image_url": "https://example.com/image-2.png",
        "category": "sci",
        "source_id": "src",
        "source_name": "src",
        "source_metadata": {},
        "summary": "this is another long summary for test validation",
    }

    # We monkeypatch internal file reading logic so it doesn't find a file during phase 2
    engine.writer.find_existing_file = MagicMock(return_value=None)
    engine._extract_slug = MagicMock(return_value="collision-test")
    engine._download_image = MagicMock(
        return_value="~/assets/images/collision-test.png"
    )

    engine.process_single_article(article1, MagicMock(), tmp_path)
    engine.process_single_article(article2, MagicMock(), tmp_path)

    from datetime import timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert (tmp_path / f"src/content/posts/{today}-collision-test.md").exists()
    assert (tmp_path / f"src/content/posts/{today}-collision-test-1.md").exists()
