"""Compatibility wrapper around :mod:`noticiencias.config_schema`."""
from __future__ import annotations

from noticiencias.config_schema import Config, DEFAULT_CONFIG, iter_field_docs

__all__ = ["Config", "DEFAULT_CONFIG", "iter_field_docs"]
