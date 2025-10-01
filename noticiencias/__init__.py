"""Utilities and configuration tooling for the Noticiencias project."""
from __future__ import annotations

from .config_manager import load_config, save_config, Config, ConfigError
from .config_schema import Config as ConfigModel, DEFAULT_CONFIG, iter_field_docs

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
