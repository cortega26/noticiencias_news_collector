from __future__ import annotations

import asyncio
from typing import Any

from news_collector.system import NewsCollectorSystem


class _FakeDatabase:
    def __init__(self) -> None:
        self.persist_calls = 0

    def save_article(self, article: Any) -> object:
        self.persist_calls += 1
        return object()

    def save_articles_bulk(self, articles: Any) -> int:
        self.persist_calls += 1
        return len(list(articles))

    def update_source_stats(self, *args: Any, **kwargs: Any) -> bool:
        self.persist_calls += 1
        return True

    def update_source_circuit_state(self, *args: Any, **kwargs: Any) -> bool:
        self.persist_calls += 1
        return True

    def update_source_feed_metadata(self, *args: Any, **kwargs: Any) -> bool:
        self.persist_calls += 1
        return True


class _FakeCollector:
    def __init__(self, db: _FakeDatabase) -> None:
        self.db = db

    async def collect_from_multiple_sources_async(
        self,
        sources: dict[str, dict[str, Any]],
        *,
        session_id: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        assert sources == {"source": {}}
        assert session_id == "session"
        assert trace_id == "trace"
        self.db.save_articles_bulk(
            [
                {"title": "Bulk one", "url": "https://example.com/one"},
                {"title": "Bulk two", "url": "https://example.com/two"},
            ]
        )
        self.db.save_article({"title": "Single", "url": "https://example.com/single"})
        self.db.update_source_stats("source", success=True)
        self.db.update_source_circuit_state("source", state="closed")
        self.db.update_source_feed_metadata("source", etag="etag")
        return {"collection_summary": {"articles_found": 3}}


def test_dry_run_captures_bulk_articles_without_persisting() -> None:
    system = NewsCollectorSystem(skip_initialization=True)
    db = _FakeDatabase()
    system.db_manager = db
    system.collector = _FakeCollector(db)

    results = asyncio.run(
        system._execute_collection(
            {"source": {}},
            dry_run=True,
            session_id="session",
            trace_id="trace",
        )
    )

    assert db.persist_calls == 0
    assert [article["title"] for article in results["articles"]] == [
        "Bulk one",
        "Bulk two",
        "Single",
    ]
    assert db.save_article.__func__ is _FakeDatabase.save_article
    assert db.save_articles_bulk.__func__ is _FakeDatabase.save_articles_bulk
    assert db.update_source_stats.__func__ is _FakeDatabase.update_source_stats
    assert (
        db.update_source_circuit_state.__func__
        is _FakeDatabase.update_source_circuit_state
    )
    assert (
        db.update_source_feed_metadata.__func__
        is _FakeDatabase.update_source_feed_metadata
    )
