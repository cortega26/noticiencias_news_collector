"""End-to-end tests verifying configuration precedence layers."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from noticiencias.config_manager import Config, load_config


def _load(
    config_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Helper to load configuration within the temporary test workspace."""

    return load_config(path=config_path, environ=environ or {})


def test_config_precedence_defaults(tmp_path: Path) -> None:
    """Defaults should be used when no configuration layers are provided."""

    config = _load(tmp_path / "config.toml")

    assert config.app.environment == "development"
    assert config.collection.async_enabled is False


def test_config_precedence_config_file_overrides_defaults(tmp_path: Path) -> None:
    """Values present in config.toml must override schema defaults."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
environment = "staging"

[collection]
async_enabled = true

[database]
driver = "postgresql"
host = "db.internal"
port = 6543
user = "collector"
password = "secret"
""".strip()
    )

    config = _load(config_path)

    assert config.app.environment == "staging"
    assert config.collection.async_enabled is True
    assert config.database.driver == "postgresql"
    assert config.database.host == "db.internal"
    assert config.database.port == 6543
    assert config.database.user == "collector"


def test_config_precedence_env_file_overrides_config_file(tmp_path: Path) -> None:
    """.env entries should take precedence over TOML configuration values."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[app]
environment = "staging"

[collection]
async_enabled = true

[rate_limiting]
max_retries = 7
""".strip()
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "NOTICIENCIAS__APP__ENVIRONMENT=production",
                "NOTICIENCIAS__COLLECTION__ASYNC_ENABLED=false",
                "NOTICIENCIAS__RATE_LIMITING__MAX_RETRIES=9",
            ]
        )
    )

    config = _load(config_path)

    assert config.app.environment == "production"
    assert config.collection.async_enabled is False
    assert config.rate_limiting.max_retries == 9


def test_config_precedence_process_env_overrides_env_file(tmp_path: Path) -> None:
    """Process environment variables should override .env entries."""

    config_path = tmp_path / "config.toml"
    config_path.write_text('[app]\nenvironment = "staging"\n')
    env_path = tmp_path / ".env"
    env_path.write_text("NOTICIENCIAS__APP__ENVIRONMENT=production\n")

    process_env = {"NOTICIENCIAS__APP__ENVIRONMENT": "test"}

    config = load_config(path=config_path, environ=process_env)

    assert config.app.environment == "test"
