"""Integration test for C-02: E2E pipeline idempotency (F-0020 gap).

Feed a static fixture with N articles, run save pipeline, verify N in DB.
Re-run with the same feed, verify still exactly N (not 2N).

Depends on B-03 (content hash dedup) being implemented.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "test_idempotency.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    yield manager
    manager.close()


def _make_article(idx: int) -> dict:
    """Build a unique, valid article payload for the given index."""
    unique_content = (
        f"Article {idx} content about scientific discovery number {idx}. "
        f"This research explores topic {idx} in depth with novel methodology. "
        * 30
    )
    return {
        "url": f"https://test-source.com/article-{idx}",
        "original_url": f"https://test-source.com/article-{idx}",
        "title": f"Scientific Discovery Number {idx} in Modern Research",
        "summary": f"Researchers have made discovery number {idx} which advances the field significantly.",
        "content": unique_content,
        "source_id": "idempotency_test",
        "source_name": "Idempotency Test Source",
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Test Author"],
        "language": "en",
        "word_count": 200,
        "reading_time_minutes": 5,
        "article_metadata": {
            "credibility_score": 0.9,
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
            "original_url": f"https://test-source.com/article-{idx}",
        },
    }


FIXTURE_SIZE = 5


class TestPipelineIdempotency:
    """C-02 / F-0020: Pipeline executed 2x with same feed produces N articles, not 2N."""

    def test_pipeline_idempotency_full(self, db_manager):
        """Run 1: insert N articles. Run 2: same articles → still N total."""
        fixture = [_make_article(i) for i in range(FIXTURE_SIZE)]

        # --- Run 1: first ingestion ---
        for article_data in fixture:
            db_manager.save_article(article_data)

        with db_manager.get_session() as session:
            count_after_run1 = session.query(Article).count()

        assert count_after_run1 == FIXTURE_SIZE, (
            f"Expected {FIXTURE_SIZE} articles after first run, got {count_after_run1}"
        )

        # --- Run 2: re-ingest same feed ---
        for article_data in fixture:
            db_manager.save_article(article_data)

        with db_manager.get_session() as session:
            count_after_run2 = session.query(Article).count()

        assert count_after_run2 == FIXTURE_SIZE, (
            f"Expected {FIXTURE_SIZE} articles after second run (idempotent), "
            f"got {count_after_run2}"
        )

    def test_new_articles_still_accepted_after_dedup(self, db_manager):
        """After dedup blocks duplicates, genuinely new articles are still inserted."""
        fixture = [_make_article(i) for i in range(FIXTURE_SIZE)]

        # Run 1
        for article_data in fixture:
            db_manager.save_article(article_data)

        # Run 2 with same + new
        new_articles = [_make_article(i + FIXTURE_SIZE) for i in range(3)]
        for article_data in fixture + new_articles:
            db_manager.save_article(article_data)

        with db_manager.get_session() as session:
            total = session.query(Article).count()

        assert total == FIXTURE_SIZE + 3, (
            f"Expected {FIXTURE_SIZE + 3} articles (original + new), got {total}"
        )
