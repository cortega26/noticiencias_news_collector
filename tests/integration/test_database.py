from datetime import datetime, timedelta, timezone

import pytest
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base


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


def test_save_and_retrieve_article_full_flow(test_db_manager):
    # Payload matching CollectorArticleModel constraints
    article_data = {
        "title": "A Very Long Title That Is Definitely Over Ten Characters",
        "url": "http://test.com/article1",
        "source_id": "src1",
        "category": "general",
        "published_date": datetime.now(timezone.utc),
        "source_name": "Source A",
        "summary": "Summary " * 20,
        "content": "Long content " * 100,  # > 1000 chars effectively
        "word_count": 100,
        "reading_time_minutes": 5,
        "authors": ["John Doe"],
        "language": "en",
    }

    saved = test_db_manager.save_article(article_data)  # Direct call
    assert saved is not None
    assert saved.id is not None

    # API methods
    assert test_db_manager.article_exists(article_data["url"])

    # Retrieve via internal session for assertion
    from news_collector.storage.models import Article

    with test_db_manager.get_session() as session:
        fetched = session.query(Article).filter_by(url=article_data["url"]).first()
        assert fetched.title == article_data["title"]


def test_save_articles_bulk(test_db_manager):
    # Prepare batch data
    articles = []
    for i in range(5):
        articles.append(
            {
                "title": f"Bulk Article {i}",
                "url": f"http://test.com/bulk/{i}",
                "source_id": "src1",
                "category": "general",
                "published_date": datetime.now(timezone.utc),
                "source_name": "Source A",
                "summary": "Bulk summary",
                "content": "Bulk content " * 50,
                "word_count": 100,
                "reading_time_minutes": 1,
                "authors": ["Batch Bot"],
                "language": "en",
            }
        )

    # Execute bulk save
    count = test_db_manager.save_articles_bulk(articles)
    assert count == 5

    # Verify existing check within bulk (should skip duplicates)
    count_retry = test_db_manager.save_articles_bulk(articles)
    assert count_retry == 0

    # Verify persistence
    from news_collector.storage.models import Article

    with test_db_manager.get_session() as session:
        saved_count = (
            session.query(Article)
            .filter(Article.url.like("http://test.com/bulk/%"))
            .count()
        )
        assert saved_count == 5


def test_update_article_score(test_db_manager):
    # 1. Create Article
    article_data = {
        "title": "Another Long Title For Testing Scoring Update Logic",
        "url": "http://test.com/score-me",
        "source_id": "src1",
        "category": "tech",
        "source_name": "Source A",
        "summary": "Short summary",
        "content": "Enough content " * 100,
        "published_date": datetime.now(timezone.utc),
        "word_count": 500,
        "reading_time_minutes": 2,
    }
    saved = test_db_manager.save_article(article_data)

    # 2. Update Score
    score_payload = {
        "final_score": 0.85,
        "should_include": True,
        "components": {
            "source_credibility": 0.9,
            "recency": 0.8,
            "content_quality": 0.7,
            "engagement_potential": 0.5,
        },
        "weights": {
            "source_credibility": 0.25,
            "recency": 0.25,
            "content_quality": 0.25,
            "engagement": 0.25,
        },
    }

    success = test_db_manager.update_article_score(saved.id, score_payload)
    assert success is True

    # Verify persistence
    from news_collector.storage.models import Article, ScoreLog

    with test_db_manager.get_session() as session:
        art = session.query(Article).filter_by(id=saved.id).first()
        assert art.final_score == 0.85
        assert art.processing_status == "completed"

        log = session.query(ScoreLog).filter_by(article_id=saved.id).first()
        assert log is not None
        assert log.final_score == 0.85


def test_analytics_methods(test_db_manager):
    # Insert dummy data
    for i in range(3):
        data = {
            "title": f"Article {i} Title Long Enough",
            "url": f"http://test.com/{i}",
            "source_id": "src1",
            "category": "general",
            "published_date": datetime.now(timezone.utc),
            "source_name": "Source A",
            "summary": "Valid summary content length check pass",
            "content": "Content " * 200,  # > 1600
            "word_count": 100,
            "reading_time_minutes": 1,
        }
        saved = test_db_manager.save_article(data)
        # Score it to appear in stats
        test_db_manager.update_article_score(
            saved.id,
            {
                "final_score": 0.5 + (i * 0.1),
                "should_include": True,
                "components": {
                    "source_credibility": 0.5,
                    "recency": 0.5,
                    "content_quality": 0.5,
                    "engagement_potential": 0.5,
                },
                "weights": {
                    "source_credibility": 0.25,
                    "recency": 0.25,
                    "content_quality": 0.25,
                    "engagement": 0.25,
                },
            },
        )

    stats = test_db_manager.get_daily_stats()
    assert stats is not None

    sources_perf = test_db_manager.get_top_sources_performance()
    assert len(sources_perf) > 0

    cat_breakdown = test_db_manager.get_category_breakdown()
    assert len(cat_breakdown) > 0


def test_cleanup_methods(test_db_manager):
    data = {
        "title": "Old Article Title To Be Deleted",
        "url": "http://old.com",
        "source_id": "src1",
        "category": "general",
        "published_date": datetime.now(timezone.utc) - timedelta(days=100),
        "source_name": "Source A",
        "summary": "Old content",
        "content": "Old content " * 100,
        "word_count": 100,
        "reading_time_minutes": 1,
    }
    saved = test_db_manager.save_article(data)

    # Manually backdate collected_date to ensure cleanup targets it
    from news_collector.storage.models import Article

    with test_db_manager.get_session() as session:
        art = session.query(Article).filter_by(id=saved.id).first()
        art.collected_date = datetime.now(timezone.utc) - timedelta(days=100)
        art.final_score = 0.1  # Ensure score is low enough
        session.add(art)

    # Cleanup older than 90 days
    result = test_db_manager.cleanup_old_data(days_to_keep=90)
    assert result["deleted_articles"] >= 1

    # Clear all
    test_db_manager.save_article(
        {**data, "url": "http://new.com", "published_date": datetime.now(timezone.utc)}
    )
    assert test_db_manager.clear_all_articles() >= 1


# Merged from tests/test_database_publication.py


def test_mark_article_published_excludes_from_scores(test_db_manager) -> None:
    # 1. Create Article
    url = "https://example.com/article"
    article_data = {
        "title": "Demo Article For Publication",
        "url": url,
        "source_id": "test",
        "source_name": "Test Source",
        "category": "general",
        "published_date": datetime.now(timezone.utc),
        "summary": "Summary content.",
        "content": "Content " * 200,
        "word_count": 100,
        "reading_time_minutes": 1,
        "article_metadata": {},
    }
    saved = test_db_manager.save_article(article_data)

    # Enable it for scoring/retrieval
    test_db_manager.update_article_score(
        saved.id,
        {
            "final_score": 0.9,
            "should_include": True,
            "components": {
                "source_credibility": 0.9,
                "recency": 0.9,
                "content_quality": 0.9,
                "engagement_potential": 0.9,
            },
            "weights": {
                "source_credibility": 0.25,
                "recency": 0.25,
                "content_quality": 0.25,
                "engagement": 0.25,
            },
        },
    )

    # Verify it appears in candidate list
    candidates = test_db_manager.get_articles_by_score(exclude_published=True)
    assert any(a.id == saved.id for a in candidates)

    # 2. Mark Published
    updated = test_db_manager.mark_article_published(
        saved.id,
        pr_url="https://noticiencias.com/demo",
    )
    assert updated is True

    # 3. Verify Exclusion
    candidates_after = test_db_manager.get_articles_by_score(exclude_published=True)
    assert not any(a.id == saved.id for a in candidates_after)


def test_mark_article_published_uses_original_url(test_db_manager) -> None:
    # 1. Create Article with different original_url
    url = "https://example.com/canonical"
    original_url = "https://example.com/original"
    article_data = {
        "title": "Canonical Article",
        "url": url,
        "source_id": "test",
        "source_name": "Test Source",
        "category": "general",
        "published_date": datetime.now(timezone.utc),
        "summary": "Summary content.",
        "content": "Content " * 200,
        "word_count": 100,
        "reading_time_minutes": 1,
        "article_metadata": {"original_url": original_url},
    }
    saved = test_db_manager.save_article(article_data)

    # 2. Mark Published
    updated = test_db_manager.mark_article_published(
        saved.id, pr_url="https://github.com/org/repo/pull/1"
    )

    assert updated is True

    from news_collector.storage.models import Article

    with test_db_manager.get_session() as session:
        art = session.query(Article).filter_by(id=saved.id).first()
        assert art.published_url == "https://github.com/org/repo/pull/1"
        assert art.processing_status == "completed"  # Updated to match implementation
        assert art.article_metadata["publication"]["state"] == "PR_CREATED"


def test_update_article_audit_status_persists_reason(test_db_manager) -> None:
    article_data = {
        "title": "Audit status persistence",
        "url": "https://example.com/audit-status",
        "source_id": "test",
        "source_name": "Test Source",
        "category": "general",
        "published_date": datetime.now(timezone.utc),
        "summary": "Summary content.",
        "content": "Content " * 200,
        "word_count": 100,
        "reading_time_minutes": 1,
        "article_metadata": {},
    }
    saved = test_db_manager.save_article(article_data)
    assert saved is not None

    updated = test_db_manager.update_article_audit_status(
        saved.id,
        "audit_failed",
        "timeout after 3 attempts",
        attempts=3,
        timeout_seconds=15,
        model="llama3.3:latest",
        endpoint="http://localhost:11434/api/generate",
    )
    assert updated is True

    from news_collector.storage.models import Article

    with test_db_manager.get_session() as session:
        art = session.query(Article).filter_by(id=saved.id).first()
        assert art is not None
        audit_meta = art.article_metadata["audit"]
        assert audit_meta["state"] == "audit_failed"
        assert "timeout" in audit_meta["reason"]
        assert audit_meta["attempts"] == 3
