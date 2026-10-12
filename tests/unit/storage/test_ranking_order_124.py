"""Plan 124 Step 2: deterministic (score, collected_date, id) ranking order.

The export path (get_articles_by_score) and the category path must use
the same 3-key order as the serving API
(score DESC, collected_date DESC, id DESC) so tied rows never flip.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "t124_step2.db"}
    )
    yield manager
    manager.close()


def _seed_tied(db_manager: DatabaseManager, n: int = 5):
    """Insert n completed rows with identical (final_score, collected_date)."""
    tied_date = datetime.now(timezone.utc) - timedelta(hours=1)
    ids = []
    with db_manager.articles._session() as session:
        for i in range(n):
            article = Article(
                url=f"https://example.com/t124-tie-{i}",
                title=f"Tied Article {i}",
                source_id="t124src",
                source_name="T124 Source",
                category="tech",
                processing_status="completed",
                final_score=0.85,
                collected_date=tied_date,
            )
            session.add(article)
            session.flush()
            ids.append(article.id)
        session.commit()
    return ids, tied_date


class TestDeterministicRankingOrder:
    def test_score_query_ties_break_by_id_desc(self, db_manager: DatabaseManager):
        ids, _ = _seed_tied(db_manager, 5)
        first = [a.id for a in db_manager.get_articles_by_score(limit=10)]
        second = [a.id for a in db_manager.get_articles_by_score(limit=10)]
        # Deterministic across runs ...
        assert first == second
        # ... and matching the serving API's 3-key order (id DESC on ties).
        assert first == sorted(ids, reverse=True)

    def test_category_query_ties_break_by_id_desc(self, db_manager: DatabaseManager):
        ids, _ = _seed_tied(db_manager, 4)
        first = [
            a.id for a in db_manager.get_articles_by_category("tech", days_back=30)
        ]
        second = [
            a.id for a in db_manager.get_articles_by_category("tech", days_back=30)
        ]
        assert first == second
        assert first == sorted(ids, reverse=True)

    def test_export_candidate_order_stable_across_runs(
        self, db_manager: DatabaseManager
    ):
        """The system/reporting.py:86-90 export path reads via
        get_articles_by_score — its candidate order must be stable."""
        ids, _ = _seed_tied(db_manager, 5)
        run_a = [
            a.id
            for a in db_manager.get_articles_by_score(
                limit=50, exclude_published=True, max_age_days=30
            )
        ]
        run_b = [
            a.id
            for a in db_manager.get_articles_by_score(
                limit=50, exclude_published=True, max_age_days=30
            )
        ]
        assert run_a == run_b == sorted(ids, reverse=True)
