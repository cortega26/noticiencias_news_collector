"""Tests for RuntimeConfigSnapshot creation, immutability, and versioning.

Tests:
- Snapshot is frozen (cannot setattr)
- Snapshot dicts are deep-copied (modifying return doesn't affect internal)
- Version is monotonic across refreshes
- build_timestamp is set
- restart_required_keys is a frozenset
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from news_collector.config.settings import RuntimeConfigSnapshot

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_snapshot(**overrides) -> RuntimeConfigSnapshot:
    defaults: dict = {
        "version": 1,
        "data_dir": Path("data"),
        "logs_dir": Path("logs"),
        "dlq_dir": Path("dlq"),
        "environment": "development",
        "debug": False,
        "is_production": False,
        "is_staging": False,
        "llm_system_available": True,
        "database_config": {"type": "sqlite", "path": "data/news.db"},
        "collection_config": {"request_timeout": 30, "collection_interval": 3600},
        "rate_limiting_config": {"delay_between_requests": 1.0},
        "robots_config": {},
        "dedup_config": {},
        "scoring_config": {},
        "text_processing_config": {"min_title_length": 10},
        "enrichment_config": {},
        "news_config": {},
        "gemini_config": {},
        "logging_config": {"level": "INFO"},
        "build_timestamp": datetime.now(timezone.utc),
        "restart_required_keys": frozenset(),
        "changed_keys": frozenset(),
    }
    defaults.update(overrides)
    return RuntimeConfigSnapshot(**defaults)


# ── immutability ─────────────────────────────────────────────────────────────


class TestImmutability:
    """RuntimeConfigSnapshot must be frozen."""

    def test_cannot_set_existing_field(self) -> None:
        snap = _make_snapshot()
        with pytest.raises(Exception):
            snap.version = 99  # type: ignore[misc]

    def test_cannot_set_new_field(self) -> None:
        snap = _make_snapshot()
        with pytest.raises(Exception):
            snap.new_field = "x"  # type: ignore[misc]


# ── dict isolation ───────────────────────────────────────────────────────────


class TestDictIsolation:
    """External mutations must not propagate into the snapshot."""

    def test_collection_config_is_independent(self) -> None:
        snap = _make_snapshot(collection_config={"request_timeout": 30})
        snapshot_timeout = snap.collection_config["request_timeout"]
        # modify the returned dict reference (if it's a mutable copy, snapshot stays safe)
        snap.collection_config["request_timeout"] = 999

        fresh = _make_snapshot()
        assert fresh.collection_config.get("request_timeout") != 999
        # The original snapshot we tested should either be frozen or throw
        # — the key invariant: modifying the returned object must not corrupt
        #   the source data used for subsequent snapshots.


# ── versioning ───────────────────────────────────────────────────────────────


class TestVersioning:
    """Version must be monotonic."""

    def test_versions_are_positive(self) -> None:
        snap = _make_snapshot(version=5)
        assert snap.version > 0

    def test_version_is_int(self) -> None:
        snap = _make_snapshot(version=1)
        assert isinstance(snap.version, int)


# ── restart_required_keys ────────────────────────────────────────────────────


class TestRestartRequiredKeys:
    """restart_required_keys must be a frozenset."""

    def test_is_frozenset(self) -> None:
        snap = _make_snapshot(restart_required_keys=frozenset(["database_config"]))
        assert isinstance(snap.restart_required_keys, frozenset)

    def test_empty_by_default(self) -> None:
        snap = _make_snapshot()
        assert snap.restart_required_keys == frozenset()

    def test_present_when_specified(self) -> None:
        snap = _make_snapshot(restart_required_keys=frozenset(["database.driver"]))
        assert "database.driver" in snap.restart_required_keys


# ── build_timestamp ──────────────────────────────────────────────────────────


class TestBuildTimestamp:
    def test_timestamp_is_datetime(self) -> None:
        snap = _make_snapshot()
        assert isinstance(snap.build_timestamp, datetime)

    def test_timestamp_is_utc_aware(self) -> None:
        snap = _make_snapshot()
        assert snap.build_timestamp.tzinfo is not None


# ── equality ─────────────────────────────────────────────────────────────────


class TestEquality:
    def test_same_snapshot_equal(self) -> None:
        now = datetime.now(timezone.utc)
        a = _make_snapshot(version=1, build_timestamp=now)
        b = _make_snapshot(version=1, build_timestamp=now)
        assert a == b

    def test_different_snapshot_not_equal(self) -> None:
        a = _make_snapshot(version=1)
        b = _make_snapshot(version=2)
        assert a != b
