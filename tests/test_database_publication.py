"""Tests for published article tracking."""

from __future__ import annotations

from pathlib import Path

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


def _create_article(
    manager: DatabaseManager, *, url: str, metadata: dict | None = None
) -> None:
    with manager.get_session() as session:
        article = Article(
            url=url,
            title="Demo",
            source_id="test",
            source_name="Test Source",
            category="general",
            processing_status="completed",
            final_score=0.9,
            article_metadata=metadata or {},
        )
        session.add(article)


def test_mark_article_published_excludes_from_scores(tmp_path: Path) -> None:
    db_path = tmp_path / "news.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})

    try:
        _create_article(manager, url="https://example.com/article")

        assert manager.get_articles_by_score(exclude_published=True)

        updated = manager.mark_article_published(
            "https://example.com/article",
            published_url="https://noticiencias.com/demo",
        )

        assert updated is True
        assert not manager.get_articles_by_score(exclude_published=True)
    finally:
        manager.close()


def test_mark_article_published_uses_original_url(tmp_path: Path) -> None:
    db_path = tmp_path / "news.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})

    try:
        _create_article(
            manager,
            url="https://example.com/canonical",
            metadata={"original_url": "https://example.com/original"},
        )

        updated = manager.mark_article_published("https://example.com/original")

        assert updated is True
    finally:
        manager.close()
