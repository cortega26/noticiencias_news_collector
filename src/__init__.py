"""
Paquete principal del News Collector System.

Contiene los módulos funcionales del sistema: colectores, scoring,
almacenamiento y utilidades.
"""

from .collectors import RSSCollector, BaseCollector
from .scoring import BasicScorer, score_multiple_articles
from .storage import get_database_manager, DatabaseManager
from .utils import get_logger, setup_logging, get_observability

__version__ = "1.0.0"
__description__ = (
    "Sistema automatizado de recopilación y scoring de noticias científicas"
)

__package_info__ = {
    "name": "news_collector",
    "version": __version__,
    "description": __description__,
    "author": "News Collector Team",
    "license": "MIT",
    "python_requires": ">=3.8",
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
    "get_observability",
]
