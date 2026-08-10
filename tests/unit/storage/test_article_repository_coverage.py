"""Unit tests for ArticleRepository write/read/scoring/delete paths.

Covers the CRUD methods, canonical-slug identity, publication helpers,
bulk scoring, and cluster helpers that the pagination suite does not touch.
Uses a real SQLite database through DatabaseManager.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.contracts.collector import CollectorArticleModel
from news_collector.contracts.scoring import ScoringRequestModel
from news_collector.storage.article_repository import (
    ensure_timezone,
    simhash_from_storage,
    simhash_normalize_unsigned,
    simhash_prefix_value,
    simhash_to_storage,
    time_distance_seconds,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, ScoreLog


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "article_repo.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    manager.initialize_sources(
        {
            "src1": {
                "url": "http://a.com",
                "name": "Source A",
                "credibility_score": 1.0,
                "category": "general",
            }
        }
    )
    yield manager
    manager.close()


def _payload(url, title="Valid title length ok", status=None, seed=None):
    unique = url.split("/")[-1] if seed is None else seed
    data = {
        "title": f"{title} {unique}",
        "url": url,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "tech",
        "published_date": datetime.now(timezone.utc),
        "content": f"Long content {unique} " * 250,
        "summary": f"Summary {unique} " * 200,
        "word_count": 100,
        "reading_time_minutes": 1,
        "authors": ["Test Author"],
        "language": "en",
    }
    if status is not None:
        data["processing_status_override"] = status
    return data


def _score_payload(final=0.8):
    return ScoringRequestModel(
        final_score=final,
        should_include=True,
        components={
            "source_credibility": 0.9,
            "recency": 0.7,
            "content_quality": 0.8,
            "engagement": 0.6,
        },
        weights={"source_credibility": 1.0},
        version="1.0",
        explanation={"why": "test"},
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_ensure_timezone_helpers():
    assert ensure_timezone(None) is None
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert ensure_timezone(naive).tzinfo == timezone.utc
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert ensure_timezone(aware) == aware


def test_simhash_helpers():
    assert simhash_normalize_unsigned(None) is None
    assert simhash_to_storage(None) is None
    assert simhash_from_storage(None) is None
    assert simhash_prefix_value(None) is None

    value = 123456789
    assert simhash_normalize_unsigned(value) == value & ((1 << 64) - 1)
    assert simhash_from_storage(simhash_to_storage(value)) == value

    negative = simhash_to_storage(value)
    assert simhash_from_storage(negative) == value


def test_time_distance_seconds():
    assert time_distance_seconds(None, datetime.now(timezone.utc)) == float("inf")
    assert time_distance_seconds(datetime.now(timezone.utc), None) == float("inf")
    a = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    b = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
    assert time_distance_seconds(a, b) == 5.0


# ---------------------------------------------------------------------------
# Save / lookup
# ---------------------------------------------------------------------------


def test_save_article_with_invalid_payload_raises(db_manager):
    with pytest.raises(ValueError):
        db_manager.articles.save_article({"url": "https://x.com/1"})
    assert db_manager.articles.save_article(_payload("https://x.com/2"))


def test_save_article_with_model_and_invalid_status(db_manager):
    model = CollectorArticleModel.model_validate(_payload("https://x.com/3"))
    with pytest.raises(ValueError):
        db_manager.articles.save_article(
            {**_payload("https://x.com/4"), "processing_status": "nonsense"}
        )
    assert isinstance(
        CollectorArticleModel.model_validate(_payload("https://x.com/5")),
        CollectorArticleModel,
    )


def test_get_article_by_id(db_manager):
    url = "https://x.com/byid"
    saved = db_manager.articles.save_article(_payload(url))
    fetched = db_manager.articles.get_article_by_id(int(saved.id))
    assert fetched is not None
    assert fetched.url == url
    assert db_manager.articles.get_article_by_id(99999) is None


def test_articles_exist_empty(db_manager):
    assert db_manager.articles.articles_exist([]) == set()


# ---------------------------------------------------------------------------
# Publication helpers
# ---------------------------------------------------------------------------


def test_publication_helpers(db_manager):
    saved = db_manager.articles.save_article(_payload("https://x.com/pub"))
    article_id = int(saved.id)

    assert db_manager.articles.is_article_published(article_id) is False
    assert db_manager.articles.is_article_published(99999) is False
    assert db_manager.articles.is_article_in_flight_or_done(99999) is False

    assert db_manager.articles.mark_article_publishing(article_id, "feat/x")
    assert db_manager.articles.is_article_in_flight_or_done(article_id) is True
    assert db_manager.articles.is_article_published(article_id) is False

    assert db_manager.articles.articles_in_flight_or_done([]) == set()
    assert db_manager.articles.published_ids_in([]) == set()
    assert {article_id} == db_manager.articles.articles_in_flight_or_done([article_id])
    assert db_manager.articles.published_ids_in([article_id]) == set()

    assert db_manager.articles.update_article_audit_status(article_id, "passed")
    assert (
        db_manager.articles.update_article_audit_status(
            article_id,
            "failed",
            reason="crit",
            attempts=2,
            timeout_seconds=30,
            model="gpt",
            endpoint="/audit",
        )
        is True
    )
    assert db_manager.articles.update_article_audit_status(99999, "failed") is False


def test_is_processed(db_manager):
    saved = db_manager.articles.save_article(_payload("https://x.com/processed"))
    article_id = int(saved.id)
    assert db_manager.articles.is_processed(str(article_id)) is False
    assert db_manager.articles.is_processed("not-a-number") is False
    assert db_manager.articles.is_processed(f"{article_id}.html") is False
    assert db_manager.articles.is_processed("another.txt") is False


# ---------------------------------------------------------------------------
# Canonical slug identity
# ---------------------------------------------------------------------------


def test_canonical_slug(db_manager):
    saved = db_manager.articles.save_article(_payload("https://x.com/slug"))
    article_id = int(saved.id)

    assert db_manager.articles.get_canonical_slug("abc") is None
    assert db_manager.articles.get_canonical_slug(article_id) is None

    assert db_manager.articles.set_canonical_slug(article_id, "mi-slug")
    assert db_manager.articles.get_canonical_slug(article_id) == "mi-slug"
    assert db_manager.articles.set_canonical_slug("abc", "x") is False
    assert db_manager.articles.set_canonical_slug(article_id, "") is False
    assert db_manager.articles.set_canonical_slug(article_id, "other-slug") is False
    assert db_manager.articles.set_canonical_slug(99999, "new-slug") is False


def test_canonical_slug_collision_with_other_article(db_manager):
    """A slug collision with a DIFFERENT article must not report the
    identity as locked (the slug must never be silently 'lost')."""
    article_a = db_manager.articles.save_article(_payload("https://x.com/a"))
    article_b = db_manager.articles.save_article(_payload("https://x.com/b"))
    slug = "shared-deterministic-slug"

    # A locks the slug first.
    assert db_manager.articles.set_canonical_slug(int(article_a.id), slug)

    # B's attempt collides at the unique index (B has no pre-existing slug,
    # so the in-memory guard passes and the DB rejects the write).
    assert db_manager.articles.set_canonical_slug(int(article_b.id), slug) is False
    # B must NOT end up with a slug that was never persisted.
    assert db_manager.articles.get_canonical_slug(int(article_b.id)) is None
    # A keeps its identity.
    assert db_manager.articles.get_canonical_slug(int(article_a.id)) == slug


# ---------------------------------------------------------------------------
# Category query and bulk validation
# ---------------------------------------------------------------------------


def test_get_articles_by_category(db_manager):
    db_manager.articles.save_article(_payload("https://x.com/cat1", status="completed"))
    db_manager.articles.save_article(_payload("https://x.com/cat2", status="completed"))
    rows = db_manager.articles.get_articles_by_category("tech", days_back=30)
    assert len(rows) == 2


def test_update_validation_status_bulk(db_manager):
    saved = db_manager.articles.save_article(_payload("https://x.com/val"))
    article_id = int(saved.id)
    assert db_manager.articles.update_validation_status_bulk([]) is True
    assert (
        db_manager.articles.update_validation_status_bulk(
            [{"id": article_id, "processing_status": "validated"}]
        )
        is True
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_update_articles_score_bulk(db_manager):
    a1 = db_manager.articles.save_article(_payload("https://x.com/s1"))
    a2 = db_manager.articles.save_article(_payload("https://x.com/s2"))

    assert db_manager.articles.update_articles_score_bulk([]) is True
    assert (
        db_manager.articles.update_articles_score_bulk(
            [(int(a1.id), _score_payload(0.7)), (int(a2.id), _score_payload(0.9))]
        )
        is True
    )

    db_manager.articles.update_articles_score_bulk(
        [(int(a1.id), {"final_score": "invalid-json"})]
    )
    assert (
        db_manager.articles.update_article_score(int(a1.id), _score_payload(0.75))
        is True
    )
    assert db_manager.articles.update_article_score(99999, _score_payload(0.5)) is False
    with pytest.raises(ValueError):
        db_manager.articles.update_article_score(int(a1.id), {"final_score": "bad"})


# ---------------------------------------------------------------------------
# Delete / clear
# ---------------------------------------------------------------------------


def test_delete_article(db_manager):
    saved = db_manager.articles.save_article(_payload("https://x.com/del"))
    article_id = int(saved.id)
    assert db_manager.articles.delete_article("abc") is False
    assert db_manager.articles.delete_article(article_id) is True
    assert db_manager.articles.delete_article(article_id) is False
    assert db_manager.articles.delete_article(99999) is False


def test_clear_all_articles(db_manager):
    db_manager.articles.save_article(_payload("https://x.com/cl1"))
    db_manager.articles.save_article(_payload("https://x.com/cl2"))
    cleared = db_manager.articles.clear_all_articles()
    assert cleared == 2
    assert db_manager.articles.get_pending_articles() == []
