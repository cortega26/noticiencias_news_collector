from __future__ import annotations

import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if "src" not in sys.modules:
    stub = types.ModuleType("src")
    stub.__path__ = [str(SRC_DIR)]
    sys.modules["src"] = stub

from src.storage.database import DatabaseManager
from src.storage.models import Article

SIMHASH_MASK = (1 << 64) - 1


def _basic_article_payload(url: str) -> dict[str, object]:
    return {
        "url": url,
        "title": "Artículo de prueba con simhash alto",
        "summary": "Resumen para pruebas de simhash.",
        "source_id": "test_source",
        "source_name": "Test Source",
        "category": "science",
    }


def test_save_article_persists_signed_simhash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "simhash.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})

    high_value = (1 << 63) | 0x12345
    monkeypatch.setattr("src.storage.database.simhash64", lambda _: high_value)

    payload = _basic_article_payload("https://example.com/high-simhash")
    payload["published_date"] = datetime(2024, 1, 2, 12, 30)  # naive on purpose

    saved = manager.save_article(payload)
    assert saved is not None

    with manager.get_session() as session:
        stored = session.query(Article).filter_by(url=payload["url"]).one()
        assert stored.simhash == high_value - (1 << 64)
        assert (
            DatabaseManager._simhash_from_storage(stored.simhash)
            == high_value & SIMHASH_MASK
        )
        assert stored.simhash_prefix == ((high_value & SIMHASH_MASK) >> 48) & 0xFFFF
        assert stored.published_date is not None
        normalized = DatabaseManager._ensure_timezone(stored.published_date)
        assert normalized is not None
        assert normalized.tzinfo is not None
        assert normalized.utcoffset() == timedelta(0)


def test_time_distance_seconds_accepts_mixed_timezone_inputs() -> None:
    aware = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2024, 1, 1, 0, 0)

    delta = DatabaseManager._time_distance_seconds(aware, naive)
    assert delta == 0.0
