"""
Paquete de colectores del News Collector System.

Incluye colectores para RSS, APIs, web scraping, etc.
"""

from .base_collector import BaseCollector, create_collector, validate_collector_result
from .rss_collector import RSSCollector

AVAILABLE_COLLECTORS = {
    "rss": RSSCollector,
}


def get_available_collector_types():
    """Retorna lista de tipos de colectores disponibles."""
    return list(AVAILABLE_COLLECTORS.keys())


def create_collector_by_name(collector_type: str):
    """Crea un colector por nombre de tipo."""
    if collector_type not in AVAILABLE_COLLECTORS:
        raise ValueError(f"Tipo de colector no disponible: {collector_type}")
    return AVAILABLE_COLLECTORS[collector_type]()


__all__ = [
    "BaseCollector",
    "RSSCollector",
    "create_collector",
    "validate_collector_result",
    "AVAILABLE_COLLECTORS",
    "get_available_collector_types",
    "create_collector_by_name",
]
