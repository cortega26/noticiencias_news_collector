"""Unit tests for AnalyticsRepository — stats, reporting, and maintenance."""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.analytics_repository import AnalyticsRepository
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base


@pytest.fixture
def analytics_db(tmp_path):
    db_file = tmp_path / "test_analytics.db"
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


def _seed_articles(manager, count: int = 3, category: str = "science") -> None:
    with manager.get_session() as session:
        now = datetime.now(timezone.utc)
        for idx in range(count):
            article = Article(
                url=f"https://example.com/{category}/{idx}",
                title=f"Analytics article {idx} with enough length",
                summary=f"Summary text for article {idx} that is long enough",
                content="C" * 501,
                source_id="src1",
                source_name="Source A",
                published_date=now,
                category=category,
                final_score=0.2 + 0.3 * idx,
                processing_status="completed",
                collected_date=now - timedelta(days=idx),
            )
            session.add(article)
        session.commit()


def test_get_collection_stats(analytics_db):
    _seed_articles(analytics_db, count=2)
    repo = AnalyticsRepository(analytics_db)
    stats = repo.get_collection_stats(days=30)
    assert len(stats) >= 1
    assert {"date", "count"} <= set(stats[0])


def test_get_source_performance(analytics_db):
    _seed_articles(analytics_db, count=2)
    repo = AnalyticsRepository(analytics_db)
    perf = repo.get_source_performance()
    assert perf[0]["source_name"] == "Source A"
    assert perf[0]["article_count"] == 2
    assert perf[0]["avg_score"] > 0.0


def test_get_category_breakdown(analytics_db):
    _seed_articles(analytics_db, count=2, category="health")
    repo = AnalyticsRepository(analytics_db)
    breakdown = repo.get_category_breakdown()
    assert {"category": "health", "count": 2} in breakdown


def test_get_score_distribution(analytics_db):
    _seed_articles(analytics_db, count=3)
    repo = AnalyticsRepository(analytics_db)
    distribution = repo.get_score_distribution(buckets=10)
    assert sum(distribution.values()) == 3


def test_get_daily_stats(analytics_db):
    _seed_articles(analytics_db, count=1)
    repo = AnalyticsRepository(analytics_db)
    stats = repo.get_daily_stats(date=datetime.now(timezone.utc))
    assert stats["articles_collected"] == 1
    assert stats["processing_rate"] == 100.0


def test_get_top_sources_performance(analytics_db):
    _seed_articles(analytics_db, count=2)
    repo = AnalyticsRepository(analytics_db)
    top = repo.get_top_sources_performance(days_back=30)
    assert top[0]["source_name"] == "Source A"
    assert top[0]["article_count"] == 2


def test_cleanup_old_data(analytics_db):
    _seed_articles(analytics_db, count=1)
    repo = AnalyticsRepository(analytics_db)
    result = repo.cleanup_old_data(days_to_keep=90)
    assert result["deleted_articles"] == 0


def test_get_health_status(analytics_db):
    repo = AnalyticsRepository(analytics_db)
    health = repo.get_health_status()
    assert isinstance(health, dict)
