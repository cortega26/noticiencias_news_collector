"""Plan 037: make bulk article persistence set-based — parity/behavior tests.

Instruments real SQLAlchemy sessions (not mocks — see plan 036's review
finding that mocks cannot catch real session/transaction bugs) to prove
query-count scaling, and that batched dedupe/clustering outcomes match
the single-save oracle, including the same-batch near-duplicate case.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, Base


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "bulk_parity.db"})
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


class _SelectCounter:
    """Counts SELECT statements issued on an engine via before_cursor_execute."""

    def __init__(self, engine):
        self.count = 0
        self._engine = engine

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            if statement.strip().upper().startswith("SELECT"):
                self.count += 1

        self._listener = _before_cursor_execute
        event.listen(engine, "before_cursor_execute", self._listener)

    def close(self):
        event.remove(self._engine, "before_cursor_execute", self._listener)


def _payload(url, title, summary, content=None, published_date=None):
    return {
        "url": url,
        "title": title,
        "summary": summary,
        "content": content or "Shared near-duplicate content body repeated. " * 30,
        "source_id": "src1",
        "source_name": "Source A",
        "category": "science",
        "published_date": published_date or datetime.now(timezone.utc),
        "word_count": 100,
        "reading_time_minutes": 5,
    }


class TestSingleSaveVsBatchClusterParity:
    """The load-bearing oracle test (per empirical investigation in spec.md):
    two near-duplicate articles must join into the same cluster with the
    same confidence whether saved sequentially or via one bulk call."""

    def test_same_batch_near_duplicates_join_like_sequential_single_saves(
        self, tmp_path
    ):
        near_dup_a = _payload(
            "https://example.com/single-a",
            "Near Duplicate Title One",
            "Same summary text here padded out.",
        )
        near_dup_b = _payload(
            "https://example.com/single-b",
            "Near Duplicate Title Two",
            "Same summary text here padded out.",
        )

        # Oracle: genuinely sequential single-item saves.
        single_manager = DatabaseManager(
            {"type": "sqlite", "path": tmp_path / "single.db"}
        )
        Base.metadata.create_all(single_manager.engine)
        single_manager.initialize_sources(
            {
                "src1": {
                    "url": "http://a.com",
                    "name": "Source A",
                    "credibility_score": 1.0,
                    "category": "general",
                }
            }
        )
        a1 = single_manager.save_article(near_dup_a)
        a2 = single_manager.save_article(near_dup_b)
        assert a1 is not None and a2 is not None
        assert a1.cluster_id == a2.cluster_id
        with single_manager.get_session() as session:
            rows = {r.url: r for r in session.query(Article).all()}
            single_conf_a = rows[near_dup_a["url"]].duplication_confidence
            single_conf_b = rows[near_dup_b["url"]].duplication_confidence
        single_manager.close()

        # Batch: one save_articles_bulk() call with both payloads together.
        batch_manager = DatabaseManager(
            {"type": "sqlite", "path": tmp_path / "batch.db"}
        )
        Base.metadata.create_all(batch_manager.engine)
        batch_manager.initialize_sources(
            {
                "src1": {
                    "url": "http://a.com",
                    "name": "Source A",
                    "credibility_score": 1.0,
                    "category": "general",
                }
            }
        )
        saved = batch_manager.save_articles_bulk([near_dup_a, near_dup_b])
        assert saved == 2
        with batch_manager.get_session() as session:
            rows = {r.url: r for r in session.query(Article).all()}
            batch_a = rows[near_dup_a["url"]]
            batch_b = rows[near_dup_b["url"]]
        batch_manager.close()

        # Same-batch near-duplicates must join, exactly like single-save.
        assert batch_a.cluster_id == batch_b.cluster_id
        assert batch_a.duplication_confidence == single_conf_a
        assert batch_b.duplication_confidence == single_conf_b
        assert batch_a.duplication_confidence > 0.0


class TestExactDuplicateDedupe:
    def test_in_batch_url_duplicate_first_wins(self, db_manager):
        payload = _payload(
            "https://example.com/dup-url", "First Title Long Enough", "Summary text."
        )
        payload_dup = _payload(
            "https://example.com/dup-url",
            "Second Different Title",
            "Different summary.",
        )
        saved = db_manager.save_articles_bulk([payload, payload_dup])
        assert saved == 1
        with db_manager.get_session() as session:
            rows = session.query(Article).filter_by(
                url="https://example.com/dup-url"
            ).all()
            assert len(rows) == 1
            assert rows[0].title == "First Title Long Enough"

    def test_in_batch_content_hash_duplicate_first_wins(self, db_manager):
        # content_hash is derived from normalized title+summary (see
        # normalize_article_text), not the `content` field — same
        # title+summary, different content/url, still collides.
        payload_a = _payload(
            "https://example.com/hash-a",
            "Shared Title For Hash Test",
            "Shared summary text for hash test.",
            content="Content body A. " * 20,
        )
        payload_b = _payload(
            "https://example.com/hash-b",
            "Shared Title For Hash Test",
            "Shared summary text for hash test.",
            content="Content body B. " * 20,
        )
        saved = db_manager.save_articles_bulk([payload_a, payload_b])
        assert saved == 1
        with db_manager.get_session() as session:
            urls = {r.url for r in session.query(Article).all()}
            assert urls == {"https://example.com/hash-a"}

    def test_existing_db_url_duplicate_skipped(self, db_manager):
        payload = _payload(
            "https://example.com/existing", "Existing Article Title", "Summary text."
        )
        first = db_manager.save_articles_bulk([payload])
        assert first == 1
        second = db_manager.save_articles_bulk([payload])
        assert second == 0


class TestSelectCountScaling:
    def test_select_count_scales_by_chunk_not_by_article_count(self, db_manager):
        articles = [
            _payload(
                f"https://example.com/scale-{i}",
                f"Scaling Title {i}",
                f"Scaling summary body number {i} padded out further.",
                content=f"Unique content body number {i}. " * 20,
            )
            for i in range(100)
        ]
        counter = _SelectCounter(db_manager.engine)
        try:
            saved = db_manager.save_articles_bulk(articles)
        finally:
            counter.close()

        assert saved == 100
        # Pre-refactor baseline measured 561 SELECTs for this exact
        # 100-article batch (~5-6 per article: URL, content-hash, and
        # up to 3 near-dup prefix queries each). The whole point of Steps
        # 2-4 is a small, roughly-constant number of chunked queries
        # instead — post-refactor this batch takes exactly 4.
        assert counter.count <= 10, (
            f"Expected a small, chunk-bounded SELECT count for 100 articles, "
            f"got {counter.count}"
        )
