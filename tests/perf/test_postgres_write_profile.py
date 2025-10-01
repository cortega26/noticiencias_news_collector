"""Performance checks for the PostgreSQL deployment profile."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.pool import QueuePool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from src.storage import models as storage_models  # noqa: E402
from src.storage.database import DatabaseManager  # noqa: E402

pytestmark = pytest.mark.perf


def _article_payload(article_id: int) -> Dict[str, Any]:
    summary = " ".join(["science"] * 120)
    now = datetime.now(timezone.utc)
    return {
        "url": f"https://example.com/articles/{article_id}",
        "original_url": f"https://example.com/articles/{article_id}?src=collector",
        "title": f"Deep Space Discovery {article_id:03d}",
        "summary": summary,
        "content": summary + f" detailed content block {article_id}",
        "source_id": "example_source",
        "source_name": "Example Source",
        "category": "space",
        "published_date": now,
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Example Author"],
        "language": "en",
        "doi": f"10.1234/example{article_id:03d}",
        "journal": "Science Daily",
        "is_preprint": False,
        "word_count": 200,
        "reading_time_minutes": 6,
    }


def test_postgres_engine_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: Dict[str, Any] = {}

    def fake_create_engine(url: Any, **kwargs: Any):
        captured["url"] = url
        captured["kwargs"] = kwargs
        sqlite_path = tmp_path / "postgres_profile.db"
        return sqlalchemy_create_engine(f"sqlite:///{sqlite_path}", echo=kwargs.get("echo", False))

    monkeypatch.setattr("src.storage.database.create_engine", fake_create_engine)

    postgres_config = {
        "type": "postgresql",
        "host": "db.internal",
        "port": 5432,
        "name": "news_collector",
        "user": "collector",
        "password": "secret",
        "connect_timeout": 5,
        "statement_timeout": 45000,
        "pool_size": 12,
        "max_overflow": 6,
        "pool_timeout": 45,
        "pool_recycle": 1200,
    }

    manager = DatabaseManager(postgres_config)

    assert captured["url"].get_backend_name() == "postgresql"
    assert captured["url"].username == "collector"
    assert captured["url"].host == "db.internal"
    kwargs = captured["kwargs"]
    assert kwargs["poolclass"] is QueuePool
    assert kwargs["pool_size"] == 12
    assert kwargs["max_overflow"] == 6
    assert kwargs["pool_timeout"] == 45
    assert kwargs["pool_recycle"] == 1200
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["connect_args"]["connect_timeout"] == 5
    assert kwargs["connect_args"]["options"] == "-c statement_timeout=45000"

    durations: List[float] = []
    total_articles = 60
    for idx in range(total_articles):
        start = perf_counter()
        stored = manager.save_article(_article_payload(idx))
        durations.append(perf_counter() - start)
        assert stored is not None

    warmup = 5
    steady_samples = durations[warmup:]
    steady_avg = sum(steady_samples) / len(steady_samples)
    assert steady_avg <= 0.05, f"Sustained insert average too slow: {steady_avg:.4f}s"
    assert max(steady_samples) <= 0.08, "Spike detected in sustained write throughput"

    with manager.get_session() as session:
        count = session.query(storage_models.Article).count()
    assert count == total_articles
