"""Compatibility wrapper exposing the new configuration manager API."""

from __future__ import annotations

from noticiencias.config_manager import (
    Config,
    ConfigError,
    ConfigMetadata,
    ConfigValueOrigin,
    load_config,
    main,
    save_config,
)

__all__ = [
    "Config",
    "ConfigError",
    "ConfigMetadata",
    "ConfigValueOrigin",
    "load_config",
    "save_config",
    "main",
]
