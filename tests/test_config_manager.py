"""Tests for the configuration manager adapters."""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

import pytest

from core.config_manager import ConfigError, ConfigManager


def _read_backups(pattern: str) -> set[Path]:
    backup_dir = Path("backups")
    if not backup_dir.exists():
        return set()
    return set(backup_dir.glob(pattern))


def test_roundtrip_env_preserves_comments_and_backup(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nAPI_KEY=abc\nDEBUG=true\n", encoding="utf-8")
    before = _read_backups(".env.*.bak")
    manager = ConfigManager(env_path)
    state = manager.load(None)
    assert state.data["API_KEY"] == "abc"
    assert state.schema.get("API_KEY").is_secret
    updated = OrderedDict(state.data)
    updated["DEBUG"] = False
    manager.save(updated)
    after = _read_backups(".env.*.bak")
    assert after - before, "Expected a backup file to be created"
    content = env_path.read_text(encoding="utf-8")
    assert "# comment" in content
    assert "DEBUG=false" in content


def test_roundtrip_yaml_profile(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("dev:\n  API_KEY: secret\n  PORT: 8080\n", encoding="utf-8")
    manager = ConfigManager(yaml_path)
    state = manager.load("dev")
    assert state.schema.get("API_KEY").is_secret
    mutable = OrderedDict(state.data)
    mutable["PORT"] = 9090
    manager.save(mutable)
    reloaded = ConfigManager(yaml_path).load("dev")
    assert reloaded.data["PORT"] == 9090


def test_roundtrip_json_nested(tmp_path: Path) -> None:
    json_path = tmp_path / "config.json"
    json_path.write_text(
        json.dumps({"debug": True, "nested": {"timeout": 30}}, indent=2),
        encoding="utf-8",
    )
    manager = ConfigManager(json_path)
    state = manager.load(None)
    assert "nested.timeout" in state.data
    mutable = OrderedDict(state.data)
    mutable["nested.timeout"] = 45
    manager.save(mutable)
    reloaded = ConfigManager(json_path).load(None)
    assert reloaded.data["nested.timeout"] == 45


def test_roundtrip_toml_headless(tmp_path: Path) -> None:
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("timeout = 30\n[paths]\nlogs = \"/tmp\"\n", encoding="utf-8")
    manager = ConfigManager(toml_path)
    manager.set_values({"timeout": "60"}, profile=None)
    state = manager.load(None)
    assert state.data["timeout"] == 60


def test_set_unknown_key_raises(tmp_path: Path) -> None:
    json_path = tmp_path / "config.json"
    json_path.write_text("{}", encoding="utf-8")
    manager = ConfigManager(json_path)
    with pytest.raises(ConfigError):
        manager.set_values({"MISSING": "1"})
