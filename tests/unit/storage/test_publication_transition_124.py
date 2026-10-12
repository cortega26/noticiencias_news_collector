"""Plan 124 Step 1: publication transitions filter in SQL.

Only named refinery_ids load — the candidate query carries the
article_metadata['publication']['refinery_id'] IN_ predicate, so a
callback naming 2 of N in-flight rows never hydrates all N.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture
def db_manager(tmp_path: Path) -> DatabaseManager:
    manager = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "t124_step1.db"}
    )
    yield manager
    manager.close()


def _make_article(url: str, idx: int) -> dict:
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
        "source_id": "t124_test",
        "source_name": "T124 Test Source",
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


def _seed_publishing(db_manager: DatabaseManager, n: int, start_idx: int = 7000):
    ids = []
    for i in range(n):
        article = db_manager.save_article(
            _make_article(f"https://example.com/t124-s1-{start_idx + i}", start_idx + i)
        )
        db_manager.mark_article_published(article.id, f"https://pr.url/{start_idx + i}")
        ids.append(article.id)
    return ids


class TestTransitionSqlFilter:
    def test_candidate_query_only_loads_named_rows(self, db_manager: DatabaseManager):
        ids = _seed_publishing(db_manager, 10)
        named = [str(ids[0]), str(ids[1])]
        with db_manager.get_session() as session:
            rows = (
                session.query(Article)
                .filter(Article.processing_status == "publishing")
                .filter(
                    Article.article_metadata["publication"]["refinery_id"]
                    .as_string()
                    .in_(named)
                )
                .all()
            )
            assert len(rows) == 2
            assert {
                str(r.article_metadata["publication"]["refinery_id"]) for r in rows
            } == set(named)

    def test_reject_only_named_rows_transition(self, db_manager: DatabaseManager):
        ids = _seed_publishing(db_manager, 5)
        updated = db_manager.reject_publication_attempts([str(ids[2])], reason="probe")
        assert updated == 1
        with db_manager.get_session() as session:
            states = {
                row.id: row.processing_status
                for row in session.query(Article).filter(Article.id.in_(ids)).all()
            }
        assert states[ids[2]] == "rejected"
        for other in ids:
            if other != ids[2]:
                assert states[other] == "publishing"

    def test_complete_only_named_rows_transition(self, db_manager: DatabaseManager):
        ids = _seed_publishing(db_manager, 5, start_idx=7100)
        updated = db_manager.complete_publication_attempts(
            [str(ids[0]), str(ids[1])], "https://x/live"
        )
        assert updated == 2
        with db_manager.get_session() as session:
            states = {
                row.id: row.processing_status
                for row in session.query(Article).filter(Article.id.in_(ids)).all()
            }
        assert states[ids[0]] == "completed"
        assert states[ids[1]] == "completed"
        for other in ids[2:]:
            assert states[other] == "publishing"
