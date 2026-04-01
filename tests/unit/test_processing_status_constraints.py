"""CRIT-06 processing status constraint tests.

These tests prove that:
- Application layer rejects invalid overrides before DB write.
- Database layer's CheckConstraint rejects invalid values on bypass.
- Valid values from PROCESSING_STATUS_VALUES persist successfully.
"""

from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base, PROCESSING_STATUS_VALUES


@pytest.fixture
def test_db_manager(tmp_path):
    db_file = tmp_path / "test_status.db"
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


def _valid_payload(url="https://example.com/test-article"):
    return {
        "url": url,
        "title": "A Valid Title sufficient length",
        "summary": "x" * 60,
        "content": "A" * 501,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "word_count": 100,
        "reading_time_minutes": 5,
    }


def test_save_article_invalid_status_override_rejected(test_db_manager):
    """Application layer validates processing_status_override before write."""
    payload = _valid_payload()

    # Needs to pass CollectorArticleModel. Extra fields aren't allowed unless we spoof the model
    # Wait, processing_status_override is allowed if we pass a dict and that dict becomes a model?
    # No, extra="forbid" in CollectorArticleModel means we can't pass 'processing_status_override'
    # in the dict directly if it's not in the schema.
    # Ah, the architecture uses `processing_status_override` by setting it as an attribute
    # on the validated model object instance during pipeline flow.
    from news_collector.contracts.collector import CollectorArticleModel

    model = CollectorArticleModel.model_validate(payload)
    setattr(model, "processing_status_override", "invalid_hacked_status")

    with pytest.raises(
        ValueError, match="Invalid processing_status: invalid_hacked_status"
    ):
        test_db_manager.save_article(model)


def test_save_articles_bulk_invalid_status_override_rejected(test_db_manager):
    """Bulk save also validates processing_status_override."""
    payload = _valid_payload("https://example.com/bulk")
    from news_collector.contracts.collector import CollectorArticleModel

    model = CollectorArticleModel.model_validate(payload)
    setattr(model, "processing_status_override", "bogus")

    with pytest.raises(ValueError, match="Invalid processing_status: bogus"):
        test_db_manager.save_articles_bulk([model])


def test_db_constraint_rejects_invalid_status(test_db_manager):
    """Database CheckConstraint prevents saving invalid status even if app logic is bypassed."""
    # We bypass save_article entirely and insert via SQLAlchemy directly
    with pytest.raises(IntegrityError):
        with test_db_manager.get_session() as session:
            article = Article(
                url="https://example.com/bypass",
                title="Bypass Test",
                source_id="src1",
                source_name="Source A",
                category="science",
                processing_status="hacked_db_status",  # INVALID
            )
            session.add(article)
            # The context manager will attempt session.commit() on exit, which will raise IntegrityError


@pytest.mark.parametrize("valid_status", PROCESSING_STATUS_VALUES)
def test_valid_status_persists_successfully(test_db_manager, valid_status):
    """All explicitly allowed statuses can be successfully persisted."""
    payload = _valid_payload(f"https://example.com/valid/{valid_status}")
    from news_collector.contracts.collector import CollectorArticleModel

    model = CollectorArticleModel.model_validate(payload)
    setattr(model, "processing_status_override", valid_status)

    saved = test_db_manager.save_article(model)

    assert saved is not None
    assert saved.processing_status == valid_status

    # Verify at DB level
    with test_db_manager.get_session() as session:
        fetched = session.query(Article).filter_by(id=saved.id).first()
        assert fetched.processing_status == valid_status
