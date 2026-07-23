"""Plan 036 Step 2: stable (collected_date, id) keyset cursor pagination.

Covers the correctness properties the plan's own Step 2 Verify demands:
equal-timestamp ties, a row inserted between two page fetches, and a full
walk that sees every starting candidate exactly once in stable order.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_collector.storage.article_repository import ArticleCursor
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base


@pytest.fixture
def db_manager(tmp_path):
    db_file = tmp_path / "pagination_test.db"
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


def _make_pending(db_manager, count, status="validated", start=None, tie_every=None):
    """Insert `count` articles with distinct/tied collected_date+id.

    tie_every, if set, makes every `tie_every`-th article share the exact
    same collected_date as its predecessor (a genuine timestamp tie).
    """
    base = start or (datetime.now(timezone.utc) - timedelta(hours=1))
    with db_manager.articles._session() as session:
        from news_collector.storage.models import Article

        last_date = base
        for i in range(count):
            if tie_every and i % tie_every != 0:
                collected = last_date
            else:
                collected = base + timedelta(minutes=i)
                last_date = collected
            article = Article(
                url=f"http://example.com/{status}-{i}",
                title=f"Article {i}",
                source_id="src1",
                source_name="Source A",
                processing_status=status,
                collected_date=collected,
            )
            session.add(article)
        session.commit()


class TestPendingPagination:
    def test_walks_every_row_exactly_once_in_stable_order(self, db_manager):
        _make_pending(db_manager, 25, status="validated")

        seen_ids = []
        cursor = None
        pages = 0
        while True:
            page = db_manager.get_pending_articles_page(
                limit=7, status="validated", cursor=cursor
            )
            if not page.items:
                break
            seen_ids.extend(a.id for a in page.items)
            pages += 1
            cursor = page.next_cursor
            if cursor is None:
                break

        assert len(seen_ids) == 25
        assert len(set(seen_ids)) == 25  # no duplicates
        assert seen_ids == sorted(seen_ids)  # stable ascending order
        assert pages == 4  # 7+7+7+4

    def test_equal_timestamps_do_not_skip_or_duplicate(self, db_manager):
        # Every article after the first shares a timestamp with it.
        _make_pending(db_manager, 10, status="validated", tie_every=100)

        seen_ids = []
        cursor = None
        while True:
            page = db_manager.get_pending_articles_page(
                limit=3, status="validated", cursor=cursor
            )
            if not page.items:
                break
            seen_ids.extend(a.id for a in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        assert len(seen_ids) == 10
        assert len(set(seen_ids)) == 10

    def test_naive_single_column_cursor_would_duplicate_or_skip_ties(self, db_manager):
        """Falsifier: a cursor keyed on collected_date alone breaks on ties."""
        _make_pending(db_manager, 6, status="validated", tie_every=100)

        with db_manager.articles._session() as session:
            from news_collector.storage.models import Article

            rows = (
                session.query(Article)
                .filter(Article.processing_status == "validated")
                .order_by(Article.collected_date, Article.id)
                .all()
            )
            first_two_ids = [r.id for r in rows[:2]]
            shared_date = rows[0].collected_date

        naive_cursor_date = shared_date
        with db_manager.articles._session() as session:
            from news_collector.storage.models import Article

            naive_next_page = (
                session.query(Article)
                .filter(Article.processing_status == "validated")
                .filter(Article.collected_date > naive_cursor_date)
                .order_by(Article.collected_date, Article.id)
                .all()
            )
        # All 6 rows share the same timestamp, so a naive `>` cursor skips
        # every remaining row after the first page — proving the tuple
        # predicate (used by get_pending_articles_page) is necessary.
        assert len(naive_next_page) == 0
        assert len(first_two_ids) == 2

    def test_final_page_returns_none_cursor(self, db_manager):
        _make_pending(db_manager, 3, status="validated")
        page = db_manager.get_pending_articles_page(limit=10, status="validated")
        assert page.next_cursor is None
        assert len(page.items) == 3

    def test_empty_result_returns_empty_page(self, db_manager):
        page = db_manager.get_pending_articles_page(limit=10, status="validated")
        assert page.items == []
        assert page.next_cursor is None

    def test_row_inserted_after_cursor_but_earlier_than_cursor_row_is_not_seen(
        self, db_manager
    ):
        """A row collected before the cursor position must never reappear,
        even if inserted into the DB after the first page was fetched —
        this is the "newly updated rows cannot reappear" property.
        """
        _make_pending(db_manager, 5, status="validated")
        page1 = db_manager.get_pending_articles_page(limit=2, status="validated")
        assert len(page1.items) == 2
        cursor = page1.next_cursor
        assert cursor is not None

        # Insert a new row stamped earlier than the cursor position.
        with db_manager.articles._session() as session:
            from news_collector.storage.models import Article

            session.add(
                Article(
                    url="http://example.com/late-insert-early-timestamp",
                    title="Late insert, early timestamp",
                    source_id="src1",
                    source_name="Source A",
                    processing_status="validated",
                    collected_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()

        page2 = db_manager.get_pending_articles_page(
            limit=10, status="validated", cursor=cursor
        )
        seen_titles = {a.title for a in page2.items}
        assert "Late insert, early timestamp" not in seen_titles


class TestRescoringPagination:
    def test_walks_every_completed_unpublished_row_once(self, db_manager):
        _make_pending(db_manager, 12, status="completed")

        seen_ids = []
        cursor = None
        while True:
            page = db_manager.get_completed_articles_for_rescoring_page(
                limit=5, days_back=30, cursor=cursor
            )
            if not page.items:
                break
            seen_ids.extend(a.id for a in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        assert len(seen_ids) == 12
        assert len(set(seen_ids)) == 12
        assert seen_ids == sorted(seen_ids)

    def test_respects_days_back_cutoff(self, db_manager):
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        _make_pending(db_manager, 3, status="completed", start=old_date)

        page = db_manager.get_completed_articles_for_rescoring_page(
            limit=10, days_back=14
        )
        assert page.items == []
