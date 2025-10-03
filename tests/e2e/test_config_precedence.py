"""End-to-end tests verifying configuration precedence layers."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Mapping, cast

import pytest

from noticiencias.config_manager import Config, load_config

CONFIG_TOML = textwrap.dedent(
    """
    [app]
    environment = "staging"

    [collection]
    async_enabled = true

    [rate_limiting]
    max_retries = 7
    """
).strip()

ENV_FILE = textwrap.dedent(
    """
    NOTICIENCIAS__APP__ENVIRONMENT=production
    NOTICIENCIAS__COLLECTION__ASYNC_ENABLED=false
    NOTICIENCIAS__RATE_LIMITING__MAX_RETRIES=9
    """
).strip()


def _load(
    config_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Helper to load configuration within the temporary test workspace."""

    return load_config(path=config_path, environ=environ or {})


@pytest.mark.parametrize(
    (
        "with_config",
        "with_env_file",
        "process_env",
        "expected_environment",
        "expected_async",
        "expected_retries",
    ),
    (
        (False, False, {}, "development", False, 3),
        (True, False, {}, "staging", True, 7),
        (True, True, {}, "production", False, 9),
        (
            True,
            True,
            {"NOTICIENCIAS__APP__ENVIRONMENT": "test"},
            "test",
            False,
            9,
        ),
    ),
)
def test_config_precedence_matrix(
    tmp_path: Path,
    with_config: bool,
    with_env_file: bool,
    process_env: Mapping[str, str],
    expected_environment: str,
    expected_async: bool,
    expected_retries: int,
) -> None:
    """Validate precedence order defaults → config → .env → process env."""

    config_path = tmp_path / "config.toml"
    env_path = tmp_path / ".env"

    if with_config:
        config_path.write_text(CONFIG_TOML, encoding="utf-8")
    if with_env_file:
        env_path.write_text(ENV_FILE, encoding="utf-8")
    else:
        env_path.touch()

    config = _load(config_path, environ=process_env)

    assert config.app.environment == expected_environment
    assert config.collection.async_enabled is expected_async
    assert config.rate_limiting.max_retries == expected_retries


def test_config_precedence_metadata_tracks_layers(tmp_path: Path) -> None:
    """The metadata should expose the precedence order for observability."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG_TOML, encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text(ENV_FILE, encoding="utf-8")

    config = load_config(
        path=config_path,
        environ={"NOTICIENCIAS__APP__ENVIRONMENT": "test"},
    )

    metadata = cast(Any, config)._metadata
    assert metadata.load_order == ("defaults", "file", "env-file", "env")
    assert metadata.provenance["app.environment"].layer == "env"
    assert metadata.provenance["collection.async_enabled"].layer == "env-file"
    assert metadata.provenance["rate_limiting.max_retries"].layer == "env-file"
