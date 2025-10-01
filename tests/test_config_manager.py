from __future__ import annotations

import os
from pathlib import Path

import pytest

from noticiencias.config_manager import Config, ConfigError, load_config, save_config
from noticiencias.config_schema import DEFAULT_CONFIG, iter_field_docs


def _flatten(mapping: dict[str, object], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for name, value in mapping.items():
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, dict):
            keys.add(path)
            keys.update(_flatten(value, path))
        else:
            keys.add(path)
    return keys


def test_precedence_env_overrides(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[collection]\nrequest_timeout_seconds = 15\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NOTICIENCIAS__COLLECTION__REQUEST_TIMEOUT_SECONDS=20\n", encoding="utf-8"
    )
    environ = {"NOTICIENCIAS__COLLECTION__REQUEST_TIMEOUT_SECONDS": "25"}
    config = load_config(config_file, environ=environ)
    assert config.collection.request_timeout_seconds == 25
    provenance = config._metadata.provenance["collection.request_timeout_seconds"]
    assert provenance.layer == "env"
    assert provenance.env_var == "NOTICIENCIAS__COLLECTION__REQUEST_TIMEOUT_SECONDS"


def test_save_config_creates_backups(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[collection]\nrequest_timeout_seconds = 10\n", encoding="utf-8")
    config = load_config(config_file)
    data = config.model_dump(mode="python")
    data["collection"]["request_timeout_seconds"] = 30
    updated = Config.model_validate(data)
    updated._metadata = config._metadata
    save_config(updated)
    data["collection"]["request_timeout_seconds"] = 40
    updated = Config.model_validate(data)
    updated._metadata = config._metadata
    save_config(updated)
    backups_dir = config_file.parent / "backups"
    backups = list(backups_dir.glob("config.toml.*.bak"))
    assert backups, "second save should produce a timestamped backup"


def test_save_config_drops_optional_none(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[database]\nport = 5432\n", encoding="utf-8")
    config = load_config(config_file)
    data = config.model_dump(mode="python")
    data["database"]["port"] = None
    updated = Config.model_validate(data)
    updated._metadata = config._metadata
    save_config(updated)
    content = config_file.read_text(encoding="utf-8")
    assert "port =" not in content


def test_blank_database_port_normalized(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[database]\nport = \"\"\n", encoding="utf-8")
    config = load_config(config_file)
    assert config.database.port is None


def test_validation_errors_report_source(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[collection]\nrequest_timeout_seconds = 'abc'\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(config_file)
    assert "collection.request_timeout_seconds" in str(excinfo.value)
    assert "file" in str(excinfo.value)


def test_schema_keys_cover_defaults() -> None:
    schema_keys = {
        entry["name"]
        for entry in iter_field_docs(DEFAULT_CONFIG)
        if not entry.get("is_nested")
    }
    default_keys = _flatten(DEFAULT_CONFIG.model_dump(mode="python"))
    assert schema_keys.issubset(default_keys)


@pytest.mark.parametrize(
    "path",
    [
        "collection.collection_interval_hours",
        "collection.max_concurrent_requests",
        "rate_limiting.domain_overrides",
        "scoring.minimum_score",
        "text_processing.supported_languages",
        "enrichment.default_model",
        "database.driver",
        "logging.level",
        "news.max_items",
    ],
)
def test_implicit_keys_are_defined(path: str) -> None:
    schema_keys = {
        entry["name"]
        for entry in iter_field_docs(DEFAULT_CONFIG)
        if not entry.get("is_nested")
    }
    assert path in schema_keys
