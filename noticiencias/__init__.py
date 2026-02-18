"""Utilities and configuration tooling for the Noticiencias project."""

from __future__ import annotations

from .config_manager import Config, ConfigError, load_config, save_config
from .config_schema import DEFAULT_CONFIG, iter_field_docs
from .config_schema import Config as ConfigModel

__all__ = [
    "load_config",
    "save_config",
    "Config",
    "ConfigError",
    "ConfigModel",
    "DEFAULT_CONFIG",
    "iter_field_docs",
]

__version__ = "0.1.0"
