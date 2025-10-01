"""
Paquete de configuración del News Collector System.

Contiene la configuración central del sistema: fuentes RSS y ajustes.
"""

from .settings import (
    DATABASE_CONFIG,
    COLLECTION_CONFIG,
    SCORING_CONFIG,
    LOGGING_CONFIG,
    TEXT_PROCESSING_CONFIG,
    RATE_LIMITING_CONFIG,
    DEDUP_CONFIG,
    ENVIRONMENT,
    IS_PRODUCTION,
    IS_STAGING,
    DEBUG,
    validate_config,
)

from .sources import (
    ALL_SOURCES,
    ELITE_JOURNALS,
    SCIENCE_MEDIA,
    INSTITUTIONAL_SOURCES,
    PREPRINT_SOURCES,
    CATEGORY_CONFIG,
    get_sources_by_category,
    get_high_credibility_sources,
    get_sources_by_update_frequency,
    validate_sources,
)

from .version import (
    MIN_PYTHON_VERSION,
    MIN_PYTHON_VERSION_STR,
    PROJECT_VERSION,
    PYTHON_REQUIRES_SPECIFIER,
    __version__,
)

__author__ = "News Collector Team"

__all__ = [
    "DATABASE_CONFIG",
    "COLLECTION_CONFIG",
    "SCORING_CONFIG",
    "LOGGING_CONFIG",
    "TEXT_PROCESSING_CONFIG",
    "RATE_LIMITING_CONFIG",
    "DEDUP_CONFIG",
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
