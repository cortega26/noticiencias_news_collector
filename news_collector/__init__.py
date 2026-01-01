"""
Paquete principal del News Collector System.

Contiene los módulos funcionales del sistema: colectores, scoring,
almacenamiento y utilidades.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from news_collector.config.version import PROJECT_VERSION, PYTHON_REQUIRES_SPECIFIER

if TYPE_CHECKING:
    from .collectors import BaseCollector, RSSCollector
    from .scoring import BasicScorer, score_multiple_articles
    from .serving import create_app
    from .storage import DatabaseManager, get_database_manager
    from .utils import get_logger, get_metrics_reporter, setup_logging

__version__ = PROJECT_VERSION
__description__ = (
    "Sistema automatizado de recopilación y scoring de noticias científicas"
)

__package_info__ = {
    "name": "news_collector",
    "version": __version__,
    "description": __description__,
    "author": "News Collector Team",
    "license": "MIT",
    "python_requires": PYTHON_REQUIRES_SPECIFIER,
}

__all__ = [
    "RSSCollector",
    "BaseCollector",
    "BasicScorer",
    "score_multiple_articles",
    "get_database_manager",
    "DatabaseManager",
    "get_logger",
    "setup_logging",
    "get_metrics_reporter",
    "create_app",
]


_LAZY_IMPORTS = {
    "RSSCollector": ".collectors",
    "BaseCollector": ".collectors",
    "BasicScorer": ".scoring",
    "score_multiple_articles": ".scoring",
    "get_database_manager": ".storage",
    "DatabaseManager": ".storage",
    "get_logger": ".utils",
    "setup_logging": ".utils",
    "get_metrics_reporter": ".utils",
    "create_app": ".serving",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_IMPORTS.get(name)
    if not module_path:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    module = import_module(module_path, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(set(__all__))
