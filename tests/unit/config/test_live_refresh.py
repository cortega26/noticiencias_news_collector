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
    RuntimeConfigSnapshot,
    get_runtime_config,
    refresh_runtime_config,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _reload_settings():
    """Return freshly reloaded settings module."""
    import importlib

    import news_collector.config.settings as mod

    return importlib.reload(mod)


@pytest.fixture(autouse=True)
def _restore_settings_module():
    """Restore the settings module after each test.

    _reload_settings() replaces news_collector.config.settings in
    sys.modules; without restoration, any later test that imported the
    original module keeps a stale reference while new importers get the
    reloaded one — breaking global state (e.g. the collector smoke test's
    system initialization). pytest-randomly surfaced this by shuffling
    order (2026-08-12). Also resets the snapshot globals so a later test's
    lazy rebuild returns the repo's real config.
    """
    import sys

    import news_collector.config.settings as mod

    yield
    sys.modules["news_collector.config.settings"] = mod
    mod._CURRENT_SNAPSHOT = None
    mod._CONFIG_STATE = None
    # Rebuild the mutable runtime holder so a later lazy refresh starts
    # from a clean RuntimeSettings (reloads mutate RUNTIME in place).
    mod.RUNTIME = type(mod.RUNTIME)()


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
        # Reload so the snapshot global belongs to THIS module instance —
        # mixing the top-level import with a reloaded module's state is
        # order-dependent (pytest-randomly surfaced it, 2026-08-12).
        mod = _reload_settings()
        snap = mod.get_runtime_config()
        assert snap is not None
        # isinstance against the RELOADED module's class — the reload
        # creates a distinct RuntimeConfigSnapshot class, so the top-level
        # import's class never matches it.
        assert isinstance(snap, mod.RuntimeConfigSnapshot)

    def test_same_version_between_refreshes(self):
        """Consecutive calls without refresh return the same snapshot."""
        mod = _reload_settings()
        snap1 = mod.get_runtime_config()
        snap2 = mod.get_runtime_config()
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


class TestGetConfigReturnsConfigNotSnapshot:

    def test_get_config_after_partial_refresh_returns_real_config(self, tmp_path):
        """Regression: get_config() must return the Config, not the snapshot.

        refresh_runtime_config() *sets* _CONFIG_STATE to the Config but
        *returns* the RuntimeConfigSnapshot (whose scoring_config is a plain
        dict). After a partial-config refresh plus the global reset that
        test_live_refresh's fixture performs, any caller that lazily
        refreshes through get_config() (e.g. the e2e harness's
        validate_config) received the snapshot and crashed with
        "'dict' object has no attribute 'weights'" (pytest-randomly
        surfaced it by running test_live_refresh before the e2e suite).
        """
        mod = _reload_settings()

        config_file = _write_toml(tmp_path, BASE_TOML)
        cfg = load_config(config_file)
        mod.refresh_runtime_config(cfg)

        # Simulate the fixture cleanup a later test sees.
        mod._CURRENT_SNAPSHOT = None
        mod._CONFIG_STATE = None
        mod.RUNTIME = type(mod.RUNTIME)()

        resolved = mod.get_config()

        # The Config has a real `scoring.weights` object; the snapshot only
        # has scoring_config as a dict. validate_config() walks .weights.
        assert hasattr(resolved, "scoring")
        assert hasattr(resolved.scoring, "weights")
        assert not isinstance(resolved, mod.RuntimeConfigSnapshot)

    def test_simplenamespace_refresh_does_not_overwrite_config_state(self, tmp_path):
        """Regression: a non-Config passed to refresh_runtime_config() must
        not overwrite _CONFIG_STATE.

        The Refinery's main() passes whatever load_config() returned; test
        doubles pass SimpleNamespace stand-ins. refresh_runtime_config()
        previously stored *any* object into _CONFIG_STATE, so a test that
        called main() with a SimpleNamespace config left _CONFIG_STATE
        pointing at an object without .scoring — the next e2e harness
        initialize() crashed in validate_config() (pytest-randomly
        surfaced it: test_main_fails_fast_when_llm_preflight_fails ran
        right before the e2e suite).
        """
        from types import SimpleNamespace

        mod = _reload_settings()
        # Prime _CONFIG_STATE with the real Config first.
        real_cfg = mod.get_config()
        assert hasattr(real_cfg, "scoring")

        fake = SimpleNamespace(
            github=SimpleNamespace(token="x"),
            ollama=SimpleNamespace(api_url="http://ollama.local"),
        )
        mod.refresh_runtime_config(fake)

        # _CONFIG_STATE must still be the real Config, not the stand-in.
        assert mod._CONFIG_STATE is real_cfg
        assert hasattr(mod._CONFIG_STATE, "scoring")
        # And the snapshot still refreshes (RUNTIME was updated).
        assert mod.get_runtime_config() is not None
