from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base


@pytest.fixture
def test_db_manager(tmp_path):
    db_file = tmp_path / "test.db"
    config = {"type": "sqlite", "path": db_file}
    manager = DatabaseManager(config)
    Base.metadata.create_all(manager.engine)
    # Init some sources
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


def test_save_article_raw_dict_canonicalizes_url(test_db_manager):
    """Prove that passing a raw dict with non-canonical URL to save_article() is safe."""
    payload1 = {
        "url": "http://www.example.com/story?utm_source=twitter",
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

    # First save
    saved1 = test_db_manager.save_article(payload1)
    assert saved1 is not None
    assert (
        str(saved1.url) == "https://example.com/story"
    ), "URL was not canonicalized at save!"

    # Second save with different raw variant
    payload2 = {
        **payload1,
        "url": "https://m.example.com/story",
    }

    saved2 = test_db_manager.save_article(payload2)
    # Should return None indicating it already exists, avoiding deduplication failure
    assert (
        saved2 is None
    ), "Identity collision! Second variant was inserted or not recognized."

    # Direct DB verification
    with test_db_manager.get_session() as session:
        articles = session.query(Article).all()
        assert len(articles) == 1
        assert str(articles[0].url) == "https://example.com/story"
