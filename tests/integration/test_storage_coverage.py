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
            # Plan 021: a PR being open is not a real publication — stays
            # "publishing", and published_at/published_url are NOT set
            # here anymore (only complete_publication_attempts sets them,
            # on a real deploy).
            assert updated.processing_status == "publishing"
            assert updated.published_url is None
            assert updated.published_at is None
            meta = dict(updated.article_metadata or {})
            assert meta.get("publication", {}).get("state") == "PR_CREATED"
            assert meta.get("publication", {}).get("pr_url") == pr_url
            assert meta.get("publication", {}).get("refinery_id") == str(article.id)
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

    def test_mark_published_persists_explicit_refinery_id(self, db_manager):
        article = db_manager.save_article(_make_article(idx=23))
        assert article is not None

        db_manager.mark_article_published(
            article.id, "https://pr.url/23", "custom-refinery-id"
        )

        with db_manager.get_session() as session:
            updated = session.query(Article).filter(Article.id == article.id).first()
            meta = dict(updated.article_metadata or {})
            assert meta["publication"]["refinery_id"] == "custom-refinery-id"

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

    def test_pr_created_article_is_not_yet_published(self, db_manager):
        """Plan 021: an open PR is not a real publication."""
        article = db_manager.save_article(
            _make_article(url="https://example.com/pub", idx=8)
        )
        assert article is not None

        db_manager.mark_article_published(article.id, "https://pr.url/1")
        assert db_manager.is_article_published(article.id) is False

    def test_completed_publication_attempt_is_published(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/deployed", idx=24)
        )
        assert article is not None

        db_manager.mark_article_published(article.id, "https://pr.url/24")
        db_manager.complete_publication_attempts(
            [str(article.id)], "https://noticiencias.com/deployed"
        )
        assert db_manager.is_article_published(article.id) is True

    def test_nonexistent_article(self, db_manager):
        assert db_manager.is_article_published(99999) is False


class TestPublishedIdsIn:
    """Batch equivalent of is_article_published (avoids N+1 in the refinery UI)."""

    def test_batch_published_filter(self, db_manager):
        # Article with published_url set (via a completed publication attempt).
        by_url = db_manager.save_article(
            _make_article(url="https://example.com/batch-url", idx=20)
        )
        db_manager.mark_article_published(by_url.id, "https://pr.url/20")
        db_manager.complete_publication_attempts(
            [str(by_url.id)], "https://noticiencias.com/batch-url"
        )

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

    def test_publishing_state_hidden_once_pr_exists(self, db_manager):
        """Plan 021: get_publishing_state must stop returning state once a PR
        exists, even though processing_status is still "publishing" — or
        PROrchestrator.attempt_recovery would re-fire after
        PUBLISHING_TIMEOUT_SECONDS on a slow-but-healthy PR and create a
        duplicate."""
        article = db_manager.save_article(
            _make_article(url="https://example.com/transition", idx=11)
        )
        assert article is not None

        db_manager.mark_article_publishing(article.id, "content/update-trans")
        state = db_manager.get_publishing_state(article.id)
        assert state is not None

        db_manager.mark_article_published(article.id, "https://pr.url/2")
        state_after = db_manager.get_publishing_state(article.id)
        assert state_after is None  # PR exists — recovery must not re-fire

        with db_manager.get_session() as session:
            updated = session.query(Article).filter(Article.id == article.id).first()
            # Still "publishing" (a PR being open isn't a real completion) —
            # only reject/complete_publication_attempts change this now.
            assert updated.processing_status == "publishing"

    def test_mark_publishing_nonexistent_article(self, db_manager):
        result = db_manager.mark_article_publishing(99999, "some-branch")
        assert result is False

    def test_get_publishing_state_nonexistent(self, db_manager):
        state = db_manager.get_publishing_state(99999)
        assert state is None


class TestPublicationAttemptTransitions:
    """Plan 021: reject/complete_publication_attempts, matched by refinery_id."""

    def test_complete_publication_attempts_sets_completed_and_url(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/complete-1", idx=30)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/30")

        updated = db_manager.complete_publication_attempts(
            [str(article.id)], "https://noticiencias.com/live"
        )
        assert updated == 1

        with db_manager.get_session() as session:
            row = session.query(Article).filter(Article.id == article.id).first()
            assert row.processing_status == "completed"
            assert row.published_url == "https://noticiencias.com/live"
            assert row.published_at is not None
            assert row.article_metadata["publication"]["state"] == "COMPLETED"

    def test_reject_publication_attempts_sets_rejected(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/reject-1", idx=31)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/31")

        updated = db_manager.reject_publication_attempts(
            [str(article.id)], reason="Content Guard failed"
        )
        assert updated == 1

        with db_manager.get_session() as session:
            row = session.query(Article).filter(Article.id == article.id).first()
            assert row.processing_status == "rejected"
            assert row.published_url is None
            assert row.article_metadata["publication"]["state"] == "REJECTED"
            assert (
                row.article_metadata["publication"]["reason"] == "Content Guard failed"
            )

    def test_unnamed_attempts_are_never_touched(self, db_manager):
        """Only refinery_ids actually named in the callback are mutated —
        never a bulk update of every 'publishing' row."""
        named = db_manager.save_article(
            _make_article(url="https://example.com/named", idx=32)
        )
        unnamed = db_manager.save_article(
            _make_article(url="https://example.com/unnamed", idx=33)
        )
        db_manager.mark_article_published(named.id, "https://pr.url/32")
        db_manager.mark_article_published(unnamed.id, "https://pr.url/33")

        db_manager.complete_publication_attempts([str(named.id)], "https://x/live")

        with db_manager.get_session() as session:
            named_row = session.query(Article).filter(Article.id == named.id).first()
            unnamed_row = (
                session.query(Article).filter(Article.id == unnamed.id).first()
            )
            assert named_row.processing_status == "completed"
            assert unnamed_row.processing_status == "publishing"

    def test_replayed_callback_is_idempotent(self, db_manager):
        """A completed attempt replayed again is a no-op, not an error."""
        article = db_manager.save_article(
            _make_article(url="https://example.com/replay", idx=34)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/34")
        db_manager.complete_publication_attempts([str(article.id)], "https://x/live")

        # Replay: candidates are only processing_status == "publishing", so
        # an already-completed attempt is simply not matched again.
        updated_again = db_manager.complete_publication_attempts(
            [str(article.id)], "https://x/live-v2"
        )
        assert updated_again == 0

        with db_manager.get_session() as session:
            row = session.query(Article).filter(Article.id == article.id).first()
            assert row.published_url == "https://x/live"  # unchanged

    def test_empty_refinery_ids_is_a_no_op(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/empty-ids", idx=35)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/35")

        assert db_manager.complete_publication_attempts([], "https://x/live") == 0
        assert db_manager.reject_publication_attempts([]) == 0

        with db_manager.get_session() as session:
            row = session.query(Article).filter(Article.id == article.id).first()
            assert row.processing_status == "publishing"


class TestArticlesInFlightOrDone:
    """Plan 021: dedup guard now checks processing_status, not published fields."""

    def test_pr_created_article_is_in_flight(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/in-flight", idx=40)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/40")
        assert db_manager.is_article_in_flight_or_done(article.id) is True

    def test_completed_article_is_in_flight_or_done(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/done", idx=41)
        )
        db_manager.mark_article_published(article.id, "https://pr.url/41")
        db_manager.complete_publication_attempts([str(article.id)], "https://x/live")
        assert db_manager.is_article_in_flight_or_done(article.id) is True

    def test_unpublished_article_is_not_in_flight(self, db_manager):
        article = db_manager.save_article(
            _make_article(url="https://example.com/not-in-flight", idx=42)
        )
        assert db_manager.is_article_in_flight_or_done(article.id) is False

    def test_batch_matches_single_article_semantics(self, db_manager):
        in_flight = db_manager.save_article(
            _make_article(url="https://example.com/batch-flight", idx=43)
        )
        not_flight = db_manager.save_article(
            _make_article(url="https://example.com/batch-not-flight", idx=44)
        )
        db_manager.mark_article_published(in_flight.id, "https://pr.url/43")

        result = db_manager.articles_in_flight_or_done([in_flight.id, not_flight.id])
        assert in_flight.id in result
        assert not_flight.id not in result

    def test_batch_empty_ids_returns_empty_set(self, db_manager):
        assert db_manager.articles_in_flight_or_done([]) == set()
