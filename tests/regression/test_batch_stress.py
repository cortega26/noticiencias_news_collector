import logging
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base

# Configure logging to show info during test execution
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_article_payload(i, url_base="http://stress.test"):
    return {
        "title": f"Stress Article {i}",
        "url": f"{url_base}/{i}",
        "source_id": "stress_src",
        "source_name": "Stress Test",
        "category": "stress",
        "published_date": datetime.now(timezone.utc),
        "summary": "Stress summary " * 10,
        "content": "Content " * 100,
        "language": "en",
        "word_count": 500,
        "reading_time_minutes": 2,
    }


def worker_batch_save(manager, articles):
    """Attempt to save a batch of articles."""
    try:
        # Use shared manager
        count = manager.save_articles_bulk(articles)
        logger.info(f"Saved {count} articles")
    except Exception as e:
        logger.error(f"Batch save failed: {e}")


@pytest.mark.regression
def test_internal_duplicates_handling():
    """Verify that save_articles_bulk handles internal duplicates without failing."""
    manager = DatabaseManager({"type": "sqlite", "path": Path(":memory:")})
    Base.metadata.create_all(manager.engine)

    # Batch with 1 unique + 2 duplicates of same URL
    batch = [
        create_article_payload(1, "http://dup.test"),
        create_article_payload(1, "http://dup.test"),  # Dup
        create_article_payload(2, "http://dup.test"),
    ]

    count = manager.save_articles_bulk(batch)
    assert count == 2, f"Expected 2 unique saves, got {count}"


@pytest.mark.regression
def test_concurrent_batches_race_condition():
    """Verify behavior under concurrent identical batch saves."""
    temp_dir = Path(tempfile.mkdtemp())
    try:
        db_file = temp_dir / "stress.db"
        manager = DatabaseManager({"type": "sqlite", "path": db_file})
        Base.metadata.create_all(manager.engine)

        # Two workers trying to save exact same batch of 10 articles at same time
        batch = [create_article_payload(i) for i in range(10)]

        # Share manager (it has check_same_thread=False)
        t1 = threading.Thread(target=worker_batch_save, args=(manager, batch))
        t2 = threading.Thread(target=worker_batch_save, args=(manager, batch))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        with manager.get_session() as session:
            total = session.query(Article).count()
            # If 0, both failed (bad). If >0, at least one succeeded.
            # If <10, partial save? (Depends on transaction isolation)
            # We mostly want to ensure NO CRASH and NO >10 (duplicates).
            assert total == 10, f"Expected 10 unique articles, got {total}"
    finally:
        shutil.rmtree(temp_dir)
