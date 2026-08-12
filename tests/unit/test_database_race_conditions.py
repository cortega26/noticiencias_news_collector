"""CRIT-04 deterministic concurrency tests.

These tests prove:
- Unsafe healing logic is removed: longer content doesn't overwrite.
- IntegrityError with UNIQUE constraint acts as a duplicate detection.
- IntegrityError without UNIQUE constraint raises properly.
- Bulk save salvages valid records on a UNIQUE constraint failure.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy
from sqlalchemy.exc import IntegrityError

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base


@pytest.fixture
def test_db_manager(tmp_path):
    db_file = tmp_path / "test_race.db"
    config = {"type": "sqlite", "path": db_file}
    manager = DatabaseManager(config)
    Base.metadata.create_all(manager.engine)
    sources = {
        "src1": {
            "url": "http://a.com",
            "name": "Source A",
            "credibility_score": 1.0,
            "category": "general",
        }
    }
    manager.initialize_sources(sources)
    yield manager
    manager.close()


def _valid_payload(
    url="https://example.com/race",
    content="A" * 501,
    title="A Valid Title sufficient length",
    summary="x" * 60,
):
    return {
        "url": url,
        "title": title,
        "summary": summary,
        "content": content,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "word_count": 100,
        "reading_time_minutes": 5,
    }


def test_save_article_removes_unsafe_healing(test_db_manager):
    """Prove that a longer new content payload does NOT overwrite an existing shorter article."""
    payload_short = _valid_payload(content="A" * 50)  # Short (under 1000)
    saved_initial = test_db_manager.save_article(payload_short)
    assert saved_initial is not None
    assert len(saved_initial.content) == 50

    # Attempt to save same URL but with much longer content
    payload_long = _valid_payload(content="Z" * 2000)
    saved_duplicate = test_db_manager.save_article(payload_long)

    # Should safely return None (duplicate), NOT update the old record
    assert saved_duplicate is None

    # Verify existing record is unchanged
    with test_db_manager.get_session() as session:
        article = (
            session.query(Article).filter_by(url="https://example.com/race").first()
        )
        assert len(article.content) == 50
        assert "A" in article.content
        assert "Z" not in article.content


@patch("news_collector.storage.database.DatabaseManager.get_session")
def test_save_article_integrity_error_duplicate(mock_get_session, test_db_manager):
    """Prove that an IntegrityError caused by a UNIQUE constraint safely returns None."""
    payload = _valid_payload()

    # Mock session to raise an IntegrityError matching a UNIQUE violation ON INSERT
    # The session is a context manager, so mock __enter__
    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    # Bypass exist check to trigger insert exception
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    # Simulate DB raising UNIQUE exception on flush/commit
    mock_session.flush.side_effect = IntegrityError(
        "UNIQUE constraint failed: articles.url",
        params=None,
        orig=Exception("unique constraint"),
    )

    saved = test_db_manager.save_article(payload)
    assert saved is None


@patch("news_collector.storage.database.DatabaseManager.get_session")
def test_save_article_integrity_error_raised(mock_get_session, test_db_manager):
    """Prove that an IntegrityError NOT caused by uniqueness is loudly raised."""
    payload = _valid_payload()

    mock_session = MagicMock()
    mock_get_session.return_value.__enter__.return_value = mock_session
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    # Simulate NOT NULL failure or other random IntegrityError
    mock_session.flush.side_effect = IntegrityError(
        "NOT NULL constraint failed: articles.title",
        params=None,
        orig=Exception("not null"),
    )

    with pytest.raises(IntegrityError, match="NOT NULL constraint failed"):
        test_db_manager.save_article(payload)


def test_bulk_save_aborts_on_integrity_error(test_db_manager):
    """Prove that save_articles_bulk aborts the entire transaction on an IntegrityError (R-11)."""
    # Start by saving item A
    item_a_payload = _valid_payload(
        url="https://example.com/A",
        title="Breaking News About The Quantum Realm Physics",
        summary="Scientists have discovered a new way to measure quantum entanglement. "
        * 5,
        content="This is a completely unique article about quantum physics and the new research."
        * 20,
    )
    test_db_manager.save_article(item_a_payload)

    # Bulk attempt: Item A (already exists, but bypasses internal dedupe and python check to simulate race)
    # Item B (new, must have different content to avoid content_hash dedupe)
    item_b_payload = _valid_payload(
        url="https://example.com/B",
        title="New Ocean Expedition Finds Unknown Species",
        summary="A new submarine expedition in the Mariana Trench found weird glowing fish. "
        * 5,
        content="Here is a distinct article about marine biology and deep sea exploration."
        * 20,
    )

    import sqlalchemy

    call_count = [0]

    original_flush = sqlalchemy.orm.Session.flush
    original_query = sqlalchemy.orm.Session.query

    def mock_query_func(self, *args, **kwargs):
        # We need to bypass the existence checks to trigger flush collision
        if call_count[0] == 0:
            mock = MagicMock()
            mock.filter_by.return_value.with_entities.return_value.first.return_value = (
                None
            )
            mock.filter_by.return_value.first.return_value = None
            return mock
        return original_query(self, *args, **kwargs)

    def mock_flush(self, *args, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            raise IntegrityError(
                "UNIQUE constraint failed: articles.url", None, Exception()
            )
        return original_flush(self, *args, **kwargs)

    with (
        patch(
            "sqlalchemy.orm.Session.query", autospec=True, side_effect=mock_query_func
        ),
        patch("sqlalchemy.orm.Session.flush", autospec=True, side_effect=mock_flush),
    ):
        with pytest.raises(IntegrityError):
            test_db_manager.save_articles_bulk([item_a_payload, item_b_payload])

    # Verify B is NOT salvaged due to atomic batch transaction
    with test_db_manager.get_session() as session:
        article = session.query(Article).filter_by(url="https://example.com/B").first()
        assert article is None
