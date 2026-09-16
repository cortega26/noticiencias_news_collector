"""Tests for SourceRepository.get_all_circuit_states (Plan 110).

One SELECT for every source — the admin sources/health endpoints use this
instead of per-source lookups.
"""

from datetime import datetime, timezone

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base


def _manager(tmp_path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "circuits.db"})
    Base.metadata.create_all(manager.engine)
    manager.initialize_sources(
        {
            "a": {
                "url": "https://a",
                "name": "A",
                "credibility_score": 0.8,
                "category": "general",
            },
            "b": {
                "url": "https://b",
                "name": "B",
                "credibility_score": 0.7,
                "category": "general",
            },
        }
    )
    return manager


def test_bulk_states_cover_all_rows_in_one_call(tmp_path):
    manager = _manager(tmp_path)
    try:
        manager.update_source_circuit_state(
            "b",
            success=False,
            force_cooldown_until=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )

        states = manager.get_all_circuit_states()

        assert set(states) == {"a", "b"}
        assert states["a"]["status"] == "ACTIVE"
        assert states["a"]["consecutive_failures"] == 0
        assert states["b"]["status"] == "COOLDOWN"
        assert states["b"]["consecutive_failures"] == 1
        assert states["b"]["next_retry_at"].isoformat().startswith("2026-09-20")
    finally:
        manager.close()


def test_unknown_source_absent_and_single_lookup_agrees(tmp_path):
    manager = _manager(tmp_path)
    try:
        assert set(manager.get_all_circuit_states()) == {"a", "b"}
        assert manager.get_source_circuit_state("ghost") is None
    finally:
        manager.close()
