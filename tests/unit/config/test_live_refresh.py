"""Tests for get_runtime_config() and refresh_runtime_config() atomic behavior.

Tests:
- get_runtime_config() returns same version between refreshes
- refresh_runtime_config() increments version
- Failed build/validation leaves old snapshot (rollback)
- Concurrent readers see consistent snapshot during refresh
- Config changes reflected in next get_runtime_config() call
"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from noticiencias.config_manager import ConfigError, load_config, save_config

from news_collector.config.settings import (
    get_runtime_config,
    refresh_runtime_config,
    RuntimeConfigSnapshot,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _reload_settings():
    """Return freshly reloaded settings module."""
    import importlib
    import news_collector.config.settings as mod

    return importlib.reload(mod)


def _write_toml(tmp_path: Path, content: str) -> Path:
    """Write a config.toml and return its path."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(content, encoding="utf-8")
    return config_file


BASE_TOML = """
[app]
environment = "development"
debug = false

[collection]
request_timeout_seconds = 30

[scoring.weights]
source_credibility = 0.25
recency = 0.25
content_quality = 0.25
engagement_potential = 0.25

[scoring.feature_weights]
source_credibility = 0.25
freshness = 0.25
content_quality = 0.25
engagement = 0.25

[database]
driver = "sqlite"
path = "news.db"
"""


# ── basic refresh ────────────────────────────────────────────────────────────


class TestBasicRefresh:

    def test_returns_snapshot_not_none(self):
        """get_runtime_config returns a valid snapshot."""
        snap = get_runtime_config()
        assert snap is not None
        assert isinstance(snap, RuntimeConfigSnapshot)

    def test_same_version_between_refreshes(self):
        """Consecutive calls without refresh return the same snapshot."""
        snap1 = get_runtime_config()
        snap2 = get_runtime_config()
        assert snap1.version == snap2.version
        assert snap1 == snap2

    def test_refresh_increments_version(self, tmp_path):
        """Refresh with a new config increments the version."""
        mod = _reload_settings()

        v1 = mod.get_runtime_config().version

        config_file = _write_toml(
            tmp_path,
            BASE_TOML.replace(
                "request_timeout_seconds = 30", "request_timeout_seconds = 60"
            ),
        )
        cfg = load_config(config_file)
        new_snap = mod.refresh_runtime_config(cfg)

        assert new_snap.version == v1 + 1
        assert new_snap.collection_config["request_timeout"] == 60

    def test_changed_keys_reported(self, tmp_path):
        """Refresh reports which keys changed between refreshes."""
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)

        config_file2 = _write_toml(
            tmp_path,
            BASE_TOML.replace(
                "request_timeout_seconds = 30", "request_timeout_seconds = 45"
            ),
        )
        cfg2 = load_config(config_file2)
        snap2 = mod.refresh_runtime_config(cfg2)

        assert "collection_config" in snap2.changed_keys


# ── rollback on validation failure ───────────────────────────────────────────


class TestRollback:

    def test_rollback_on_validate_failure(self, tmp_path):
        """When validate_config raises, the previous snapshot is preserved."""
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        initial = mod.refresh_runtime_config(cfg)
        v_initial = initial.version

        with patch.object(
            mod, "validate_config", side_effect=ConfigError("test rollback")
        ):
            with pytest.raises(ConfigError):
                mod.refresh_runtime_config(cfg)

        after = mod.get_runtime_config()
        assert after.version == v_initial
        assert after == initial

    def test_database_config_unchanged_after_rollback(self, tmp_path):
        """Database config must be preserved after failed refresh."""
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        initial = mod.refresh_runtime_config(cfg)
        orig_db = dict(initial.database_config)

        with patch.object(
            mod, "validate_config", side_effect=ConfigError("test rollback")
        ):
            try:
                mod.refresh_runtime_config(cfg)
            except ConfigError:
                pass

        after = mod.get_runtime_config()
        assert after.database_config == orig_db


# ── concurrent access ────────────────────────────────────────────────────────


class TestConcurrentAccess:

    def test_concurrent_readers_no_corruption(self):
        """Multiple threads reading concurrently get consistent snapshots."""
        mod = _reload_settings()

        errors = []
        versions_seen: list[int] = []

        def reader():
            try:
                for _ in range(50):
                    s = mod.get_runtime_config()
                    v = s.version
                    assert v >= 1, f"version < 1: {v}"
                    assert s.collection_config is not None
                    assert s.database_config is not None
                    versions_seen.append(v)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Reader errors: {errors}"

    def test_reader_sees_consistent_snapshot(self, tmp_path):
        """Readers between refresh see either old or new snapshot, never partial."""
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)
        old_version = mod.get_runtime_config().version

        saw_old = False
        for i in range(10):
            pre = mod.get_runtime_config()

            config_file2 = _write_toml(
                tmp_path,
                BASE_TOML.replace(
                    "request_timeout_seconds = 30",
                    f"request_timeout_seconds = {100 + i}",
                ),
            )
            cfg2 = load_config(config_file2)
            mod.refresh_runtime_config(cfg2)

            post = mod.get_runtime_config()
            if pre.version == old_version:
                saw_old = True
            assert pre.version <= post.version

        assert saw_old


# ── restart_required detection ───────────────────────────────────────────────


class TestRestartRequiredDetection:

    def test_database_driver_change_flags_restart(self, tmp_path):
        """Switching db driver must set restart_required."""
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)

        pg_toml = """
[app]
environment = "development"
debug = false

[collection]
request_timeout_seconds = 30

[scoring.weights]
source_credibility = 0.25
recency = 0.25
content_quality = 0.25
engagement_potential = 0.25

[scoring.feature_weights]
source_credibility = 0.25
freshness = 0.25
content_quality = 0.25
engagement = 0.25

[database]
driver = "postgresql"
host = "localhost"
port = 5432
user = "postgres"
password = "secret"
name = "noticiencias"
"""
        pg_file = _write_toml(tmp_path, pg_toml)
        pg_cfg = load_config(pg_file)
        snap = mod.refresh_runtime_config(pg_cfg)

        assert "database_config" in snap.restart_required_keys


# ── backward compatibility ───────────────────────────────────────────────────


class TestBackwardCompatibility:

    def test_runtime_still_updated(self, tmp_path):
        """RUNTIME object should still be updated for backward compat."""
        mod = _reload_settings()

        config_file = _write_toml(
            tmp_path,
            BASE_TOML.replace(
                "request_timeout_seconds = 30", "request_timeout_seconds = 77"
            ),
        )
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)

        assert mod.RUNTIME.collection_config["request_timeout"] == 77

    def test_module_getattr_still_works(self, tmp_path):
        """settings.COLLECTION_CONFIG (__getattr__) returns live values."""
        mod = _reload_settings()

        config_file = _write_toml(
            tmp_path,
            BASE_TOML.replace(
                "request_timeout_seconds = 30", "request_timeout_seconds = 88"
            ),
        )
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)

        assert mod.COLLECTION_CONFIG["request_timeout"] == 88
