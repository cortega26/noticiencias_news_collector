"""Config package with lazy attribute loading to avoid heavy imports during packaging."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Iterable

__all__ = [
    "DATABASE_CONFIG",
    "COLLECTION_CONFIG",
    "SCORING_CONFIG",
    "LOGGING_CONFIG",
    "TEXT_PROCESSING_CONFIG",
    "ENRICHMENT_CONFIG",
    "RATE_LIMITING_CONFIG",
    "DEDUP_CONFIG",
    "NEWS_CONFIG",
    "ENVIRONMENT",
    "IS_PRODUCTION",
    "IS_STAGING",
    "DEBUG",
    "validate_config",
    "ALL_SOURCES",
    "ELITE_JOURNALS",
    "SCIENCE_MEDIA",
    "INSTITUTIONAL_SOURCES",
    "PREPRINT_SOURCES",
    "CATEGORY_CONFIG",
    "get_sources_by_category",
    "get_high_credibility_sources",
    "get_sources_by_update_frequency",
    "validate_sources",
    "MIN_PYTHON_VERSION",
    "MIN_PYTHON_VERSION_STR",
    "PROJECT_VERSION",
    "PYTHON_REQUIRES_SPECIFIER",
    "__version__",
]

_MODULE_ATTRS: Dict[str, Iterable[str]] = {
    "config.settings": [
        "DATABASE_CONFIG",
        "COLLECTION_CONFIG",
        "SCORING_CONFIG",
        "LOGGING_CONFIG",
        "TEXT_PROCESSING_CONFIG",
        "ENRICHMENT_CONFIG",
        "RATE_LIMITING_CONFIG",
        "DEDUP_CONFIG",
        "NEWS_CONFIG",
        "ENVIRONMENT",
        "IS_PRODUCTION",
        "IS_STAGING",
        "DEBUG",
        "validate_config",
    ],
    "config.sources": [
        "ALL_SOURCES",
        "ELITE_JOURNALS",
        "SCIENCE_MEDIA",
        "INSTITUTIONAL_SOURCES",
        "PREPRINT_SOURCES",
        "CATEGORY_CONFIG",
        "get_sources_by_category",
        "get_high_credibility_sources",
        "get_sources_by_update_frequency",
        "validate_sources",
    ],
    "config.version": [
        "MIN_PYTHON_VERSION",
        "MIN_PYTHON_VERSION_STR",
        "PROJECT_VERSION",
        "PYTHON_REQUIRES_SPECIFIER",
        "__version__",
    ],
}

_ATTR_TO_MODULE: Dict[str, str] = {
    attribute: module for module, attributes in _MODULE_ATTRS.items() for attribute in attributes
}


def __getattr__(name: str) -> Any:
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module 'config' has no attribute {name!r}")
    module = import_module(module_name)
    for attribute in _MODULE_ATTRS[module_name]:
        globals()[attribute] = getattr(module, attribute)
    return globals()[name]


__author__ = "News Collector Team"
