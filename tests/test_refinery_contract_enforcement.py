import logging
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from pathlib import Path
from news_collector.contracts.adapters import adapt_export_article_to_collector_payload
from news_collector.logic.workflows.refinery_engine import RefineryEngine


def test_process_single_article_enforces_contract(tmp_path):
    engine = RefineryEngine(MagicMock(), MagicMock(), MagicMock(), MagicMock())

    # Track side effects
    engine.db.set_canonical_slug = MagicMock()
    engine.editor = MagicMock()
    engine.editor.process_article = MagicMock()

    invalid_article = {"id": "123"}

    result = engine.process_single_article(invalid_article, MagicMock(), tmp_path)

    assert (
        result is False
    ), "Expected process_single_article to return False for invalid article"

    # Assert no side effects
    assert (
        engine.db.set_canonical_slug.call_count == 0
    ), "DB persist should not be called"
    assert engine.editor.process_article.call_count == 0, "Editor should not be called"
    assert list(tmp_path.rglob("*.md")) == [], "No files should be written"

    valid_article = {
        "id": "123",
        "title": "Valid title 123",
        "summary": "This is a sufficiently long summary for testing",
        "content": "Valid content",
        "url": "https://example.com",
        "category": "science",
        "source_id": "test",
        "source_name": "test",
        "published_date": datetime(2024, 1, 1),
        "source_metadata": {},
    }

    engine.db.get_canonical_slug.return_value = None
    # engine.editor was mocked above, but we reuse it
    engine.editor.process_article.return_value = "content"
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 10.0}
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False
    engine.git = MagicMock()

    result = engine.process_single_article(valid_article, MagicMock(), tmp_path)
    assert result is True


def test_process_single_article_accepts_legacy_export_after_adapter(tmp_path):
    engine = RefineryEngine(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    engine.db.set_canonical_slug = MagicMock()
    engine.db.get_canonical_slug.return_value = None
    engine.editor = MagicMock()
    engine.editor.process_article.return_value = "content"
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {"epistemic_rigor_score": 10.0}
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False
    engine.git = MagicMock()

    legacy_export_article = {
        "id": "160",
        "title": "Legacy export without source_id for publish flow",
        "summary": "This is a sufficiently long summary for testing",
        "content": "Valid content",
        "url": "https://example.com/legacy",
        "category": "science",
        "source_name": "Lil'Log",
        "published_date": datetime(2024, 1, 1).isoformat(),
    }
    normalized = adapt_export_article_to_collector_payload(
        legacy_export_article, source_name_to_id={"lil'log": "lilian_weng"}
    )

    result = engine.process_single_article(normalized, MagicMock(), tmp_path)

    assert normalized["source_id"] == "lilian_weng"
    assert result is True
    assert engine.git.create_pull_request.call_count == 1
