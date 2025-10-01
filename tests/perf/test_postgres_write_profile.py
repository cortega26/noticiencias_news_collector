"""Performance checks for the PostgreSQL deployment profile."""

from __future__ import annotations

import json
import sys
import statistics
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
        "url": f"https://orbital-insights.local/articles/{article_id}",
        "original_url": f"https://orbital-insights.local/articles/{article_id}?src=collector",
        "title": f"Deep Space Discovery {article_id:03d}",
        "summary": summary,
        "content": summary + f" detailed content block {article_id}",
        "source_id": "orbital_feed",
        "source_name": "Orbital Science Desk",
        "category": "space",
        "published_date": now,
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["A. Researcher"],
        "language": "en",
        "doi": f"10.1234/orbital{article_id:03d}",
        "journal": "Science Daily",
        "is_preprint": False,
        "word_count": 200,
        "reading_time_minutes": 6,
    }


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = percentile * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


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
    assert max(steady_samples) <= 0.16, "Spike detected in sustained write throughput"

    with manager.get_session() as session:
        count = session.query(storage_models.Article).count()
    assert count == total_articles

    perf_reports_dir = PROJECT_ROOT.parent / "reports" / "perf"
    perf_reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = perf_reports_dir / "postgres_write_profile.json"
    captured_url = captured["url"]
    if hasattr(captured_url, "render_as_string"):
        safe_dsn = captured_url.render_as_string(hide_password=True)
    else:
        safe_dsn = str(captured_url)
    captured_kwargs = captured["kwargs"]

    log_payload = {
        "backend": {
            "dsn": safe_dsn,
            "pool": {
                "size": captured_kwargs.get("pool_size"),
                "max_overflow": captured_kwargs.get("max_overflow"),
                "timeout": captured_kwargs.get("pool_timeout"),
                "recycle": captured_kwargs.get("pool_recycle"),
            },
        },
        "total_articles": total_articles,
        "warmup_samples": warmup,
        "metrics": {
            "mean_seconds": statistics.fmean(steady_samples),
            "p95_seconds": _percentile(steady_samples, 0.95),
            "max_seconds": max(steady_samples),
        },
    }
    report_path.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")
    print(f"postgres_write_profile_log={report_path}")
