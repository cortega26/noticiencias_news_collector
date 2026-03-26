"""Integration test for B-03: Content hash dedup independent of URL check (F-0019).

Verifies that two articles with different URLs but identical content are
correctly deduplicated by content hash.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.storage.database import DatabaseManager


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "test_dedup.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    yield manager
    manager.close()


def _make_article(url: str, title: str, summary: str, content: str) -> dict:
    """Build a minimal valid article payload."""
    return {
        "url": url,
        "original_url": url,
        "title": title,
        "summary": summary,
        "content": content,
        "source_id": "test_source",
        "source_name": "Test Source",
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
            "original_url": url,
        },
    }


SHARED_TITLE = "Breakthrough Discovery in Quantum Physics Research"
SHARED_SUMMARY = (
    "Scientists have achieved a major breakthrough in quantum physics "
    "that could transform computing technology for future generations."
)
SHARED_CONTENT = (
    "In a remarkable development, researchers at the Institute for Advanced Study "
    "have demonstrated a novel approach to quantum error correction that dramatically "
    "reduces the overhead needed for fault-tolerant quantum computing. The team's paper, "
    "published today, describes a method that achieves error rates below the threshold "
    "needed for practical quantum computation. This breakthrough represents years of "
    "collaborative research spanning multiple disciplines and institutions. "
    * 20
)


class TestContentHashDedupCrossURL:
    """B-03 / F-0019: Same content arriving from different URLs must be deduplicated."""

    def test_same_content_different_urls_rejected(self, db_manager):
        """Article B with URL-2 but identical content to article A (URL-1) is rejected."""
        article_a = _make_article(
            url="https://source-a.com/quantum-breakthrough",
            title=SHARED_TITLE,
            summary=SHARED_SUMMARY,
            content=SHARED_CONTENT,
        )
        article_b = _make_article(
            url="https://source-b.com/quantum-discovery",
            title=SHARED_TITLE,
            summary=SHARED_SUMMARY,
            content=SHARED_CONTENT,
        )

        result_a = db_manager.save_article(article_a)
        assert result_a is not None, "First article should be saved"

        result_b = db_manager.save_article(article_b)
        assert result_b is None, "Second article with same content should be rejected as duplicate"

    def test_different_content_different_urls_accepted(self, db_manager):
        """Two articles with different URLs AND different content are both saved."""
        article_a = _make_article(
            url="https://source-a.com/article-one",
            title="First Article About Biology",
            summary="A comprehensive study on marine biology and ocean ecosystems.",
            content="Marine biology research content that is unique and different. " * 30,
        )
        article_b = _make_article(
            url="https://source-b.com/article-two",
            title="Second Article About Chemistry",
            summary="An innovative approach to organic chemistry synthesis methods.",
            content="Organic chemistry research content that is completely different. " * 30,
        )

        result_a = db_manager.save_article(article_a)
        assert result_a is not None

        result_b = db_manager.save_article(article_b)
        assert result_b is not None

    def test_same_url_still_rejected(self, db_manager):
        """URL dedup still works as before (regression check)."""
        article = _make_article(
            url="https://source-a.com/same-url",
            title=SHARED_TITLE,
            summary=SHARED_SUMMARY,
            content=SHARED_CONTENT,
        )

        result_a = db_manager.save_article(article)
        assert result_a is not None

        result_b = db_manager.save_article(article)
        assert result_b is None
