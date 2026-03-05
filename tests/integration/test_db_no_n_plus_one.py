import pytest
from datetime import datetime, timezone
from sqlalchemy import event
from sqlalchemy.engine import Engine
from news_collector.storage.database import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "test.db"})
    yield manager
    manager.close()


def _get_valid_article(i: int) -> dict:
    return {
        "url": f"http://test.com/valid/long/url/{i}",
        "title": f"A very long valid title for article {i}",
        "content": "This is a long enough content to pass the validation rule. " * 10,
        "summary": "Valid summary",
        "source_name": "Test Source",
        "category": "technology",
        "published_date": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "source_id": "test",
    }


def test_validation_bulk_update_no_n_plus_one(db_manager):
    articles = [_get_valid_article(i) for i in range(10)]
    for art in articles:
        db_manager.save_article(art)

    pending = db_manager.get_pending_articles()
    assert len(pending) == 10

    query_count = 0

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        nonlocal query_count
        query_count += 1

    event.listen(Engine, "before_cursor_execute", before_cursor_execute)

    try:
        mappings = [{"id": art.id, "processing_status": "validated"} for art in pending]
        db_manager.update_validation_status_bulk(mappings)
    finally:
        event.remove(Engine, "before_cursor_execute", before_cursor_execute)

    assert (
        query_count < 10
    ), f"Expected constant queries, got {query_count} for 10 items"


def test_scoring_bulk_update_no_n_plus_one(db_manager):
    articles = [_get_valid_article(i + 100) for i in range(10)]
    for art in articles:
        db_manager.save_article(art)

    pending = db_manager.get_pending_articles()

    score_data = []
    for art in pending:
        score_data.append(
            (
                art.id,
                {
                    "final_score": 0.9,
                    "components": {
                        "source_credibility": 0.8,
                        "content_quality": 0.9,
                        "recency": 1.0,
                        "engagement": 0.7,
                    },
                    "should_include": True,
                    "version": "1.0",
                    "weights": {},
                    "explanation": {},
                },
            )
        )

    query_count = 0

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        nonlocal query_count
        query_count += 1

    event.listen(Engine, "before_cursor_execute", before_cursor_execute)

    try:
        db_manager.update_articles_score_bulk(score_data)
    finally:
        event.remove(Engine, "before_cursor_execute", before_cursor_execute)

    assert (
        query_count < 15
    ), f"Expected constant queries, got {query_count} for 10 items"
