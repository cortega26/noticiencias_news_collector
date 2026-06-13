"""Integration tests for C-01: Coverage expansion to storage/ and logic/workflows/ (F-0020).

Tests critical paths in DatabaseManager:
- mark_article_published
- set_canonical_slug
- save_article dedup paths
- is_article_published
- publishing state transitions (B-01)
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "test_storage_coverage.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})
    yield manager
    manager.close()


def _make_article(url: str = "https://example.com/test", idx: int = 0) -> dict:
    """Build a minimal valid article payload."""
    unique_content = (
        f"Article {idx} about scientific discovery. "
        f"This research explores novel methodology in depth. " * 30
    )
    return {
        "url": url,
        "original_url": url,
        "title": f"Test Article Title Number {idx} About Science",
        "summary": f"A sufficiently long summary for article {idx} that passes validation requirements.",
        "content": unique_content,
        "source_id": "coverage_test",
        "source_name": "Coverage Test Source",
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


class TestMarkArticlePublished:
    """Tests for mark_article_published."""

    def test_mark_published_sets_status_and_url(self, db_manager):
        article = db_manager.save_article(_make_article(idx=1))
        assert article is not None

        pr_url = "https://github.com/owner/repo/pull/42"
        result = db_manager.mark_article_published(article.id, pr_url)
        assert result is True

        with db_manager.get_session() as session:
            updated = session.query(Article).filter(Article.id == article.id).first()
            assert updated.processing_status == "completed"
            assert updated.published_url == pr_url
            assert updated.published_at is not None
            meta = dict(updated.article_metadata or {})
            assert meta.get("publication", {}).get("state") == "PR_CREATED"
            assert meta.get("publication", {}).get("pr_url") == pr_url
            assert (
                meta.get("publication", {}).get("frontend_checks", {}).get("state")
                == "pending"
            )
            assert (
                meta.get("publication", {})
                .get("frontend_checks", {})
                .get("ready_for_merge")
                is False
            )

    def test_mark_published_nonexistent_article(self, db_manager):
        result = db_manager.mark_article_published(99999, "https://pr.url")
        assert result is False


class TestSetCanonicalSlug:
    """Tests for set_canonical_slug."""

    def test_set_slug_persists(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/slug-test", idx=2)
        )
        assert article is not None

        result = db_manager.set_canonical_slug(article.id, "2024-01-01-test-slug")
        assert result is True

        slug = db_manager.get_canonical_slug(article.id)
        assert slug == "2024-01-01-test-slug"

    def test_set_slug_immutable(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/immutable-slug", idx=3)
        )
        assert article is not None

        db_manager.set_canonical_slug(article.id, "2024-01-01-original")
        result = db_manager.set_canonical_slug(article.id, "2024-01-01-different")
        assert result is False

        slug = db_manager.get_canonical_slug(article.id)
        assert slug == "2024-01-01-original"

    def test_set_slug_invalid_id(self, db_manager):
        result = db_manager.set_canonical_slug("not-a-number", "slug")
        assert result is False

    def test_set_slug_empty(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/empty-slug", idx=4)
        )
        result = db_manager.set_canonical_slug(article.id, "")
        assert result is False


class TestSaveArticleDedupPaths:
    """Tests for save_article dedup paths."""

    def test_url_dedup(self, db_manager):
        url = "https://example.com/unique-url-dedup"
        a1 = db_manager.save_article(_make_article(url=url, idx=5))
        assert a1 is not None

        a2 = db_manager.save_article(_make_article(url=url, idx=5))
        assert a2 is None

    def test_content_hash_dedup(self, db_manager):
        """Same content, different URLs → second rejected."""
        a1 = db_manager.save_article(
            _make_article(url="https://source-a.com/content-dedup", idx=6)
        )
        assert a1 is not None

        payload_b = _make_article(url="https://source-b.com/content-dedup", idx=6)
        a2 = db_manager.save_article(payload_b)
        assert a2 is None


class TestIsArticlePublished:
    """Tests for is_article_published."""

    def test_unpublished_article(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/unpub", idx=7)
        )
        assert article is not None
        assert db_manager.is_article_published(article.id) is False

    def test_published_article(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/pub", idx=8)
        )
        assert article is not None

        db_manager.mark_article_published(article.id, "https://pr.url/1")
        assert db_manager.is_article_published(article.id) is True

    def test_nonexistent_article(self, db_manager):
        assert db_manager.is_article_published(99999) is False


class TestPublishedIdsIn:
    """Batch equivalent of is_article_published (avoids N+1 in the refinery UI)."""

    def test_batch_published_filter(self, db_manager):
        # Article with published_url set (via mark_article_published).
        by_url = db_manager.save_article(
            _make_article(url="https://example.com/batch-url", idx=20)
        )
        db_manager.mark_article_published(by_url.id, "https://pr.url/20")

        # Article with only published_at set (no published_url).
        by_date = db_manager.save_article(
            _make_article(url="https://example.com/batch-date", idx=21)
        )
        with db_manager.get_session() as session:
            row = session.query(Article).filter(Article.id == by_date.id).first()
            row.published_at = datetime.now(timezone.utc)
            session.add(row)

        # Unpublished article (neither field set).
        unpublished = db_manager.save_article(
            _make_article(url="https://example.com/batch-unpub", idx=22)
        )

        result = db_manager.published_ids_in([by_url.id, by_date.id, unpublished.id])
        assert by_url.id in result
        assert by_date.id in result
        assert unpublished.id not in result

    def test_empty_ids_returns_empty_set(self, db_manager):
        assert db_manager.published_ids_in([]) == set()


class TestPublishingStateTransitions:
    """B-01 / C-01: Tests for publishing state transitions."""

    def test_mark_publishing_sets_state(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/pub-state", idx=9)
        )
        assert article is not None

        result = db_manager.mark_article_publishing(article.id, "content/update-test")
        assert result is True

        state = db_manager.get_publishing_state(article.id)
        assert state is not None
        assert state["publishing_branch"] == "content/update-test"
        assert state["publishing_started_at"] is not None

    def test_get_publishing_state_not_in_publishing(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/not-pub", idx=10)
        )
        assert article is not None

        state = db_manager.get_publishing_state(article.id)
        assert state is None

    def test_publishing_to_completed_transition(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/transition", idx=11)
        )
        assert article is not None

        db_manager.mark_article_publishing(article.id, "content/update-trans")
        state = db_manager.get_publishing_state(article.id)
        assert state is not None

        db_manager.mark_article_published(article.id, "https://pr.url/2")
        state_after = db_manager.get_publishing_state(article.id)
        assert state_after is None  # No longer in publishing state

        with db_manager.get_session() as session:
            updated = session.query(Article).filter(Article.id == article.id).first()
            assert updated.processing_status == "completed"

    def test_mark_publishing_nonexistent_article(self, db_manager):
        result = db_manager.mark_article_publishing(99999, "some-branch")
        assert result is False

    def test_get_publishing_state_nonexistent(self, db_manager):
        state = db_manager.get_publishing_state(99999)
        assert state is None
