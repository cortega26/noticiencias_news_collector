"""Plan 124 Step 3: legacy unbounded reads migrate to bounded/keyset reads.

- Keyset rescore pages return the same set as the deprecated unbounded
  ``get_completed_articles_for_rescoring`` on fixtures.
- ``get_articles_by_category(limit=...)`` returns the top-N prefix of the
  unbounded read in the same deterministic order.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "t124_step3.db"}
    )
    yield manager
    manager.close()


def _seed_completed(db_manager: DatabaseManager, n: int, category: str = "tech"):
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    with db_manager.articles._session() as session:
        for i in range(n):
            session.add(
                Article(
                    url=f"https://example.com/t124-s3-{category}-{i}",
                    title=f"S3 {category} Article {i}",
                    source_id="t124s3",
                    source_name="T124 S3 Source",
                    category=category,
                    processing_status="completed",
                    final_score=float(i % 5) * 0.1,
                    collected_date=base + timedelta(minutes=i),
                )
            )
        session.commit()


def _walk_rescore_pages(db_manager: DatabaseManager, limit: int, days_back: int):
    seen = []
    cursor = None
    while True:
        page = db_manager.get_completed_articles_for_rescoring_page(
            limit=limit, days_back=days_back, cursor=cursor
        )
        if not page.items:
            break
        seen.extend(a.id for a in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    return seen


class TestLegacyMigration:
    def test_keyset_pages_match_legacy_rescore_set(
        self, db_manager: DatabaseManager
    ):
        _seed_completed(db_manager, 12)
        legacy_ids = sorted(
            a.id
            for a in db_manager.articles.get_completed_articles_for_rescoring(
                days_back=30
            )
        )
        paged_ids = sorted(_walk_rescore_pages(db_manager, limit=5, days_back=30))
        assert paged_ids == legacy_ids
        assert len(paged_ids) == 12

    def test_bounded_category_read_is_top_n_prefix(
        self, db_manager: DatabaseManager
    ):
        _seed_completed(db_manager, 8)
        full = db_manager.articles.get_articles_by_category("tech", days_back=30)
        bounded = db_manager.articles.get_articles_by_category(
            "tech", days_back=30, limit=3
        )
        assert len(full) == 8
        assert [a.id for a in bounded] == [a.id for a in full[:3]]

    def test_unbounded_category_default_preserved(
        self, db_manager: DatabaseManager
    ):
        _seed_completed(db_manager, 4)
        rows = db_manager.articles.get_articles_by_category("tech", days_back=30)
        assert len(rows) == 4
