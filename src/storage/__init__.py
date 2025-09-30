"""
Paquete de storage del News Collector System.

Gestiona persistencia de datos, modelos y conexión a la base de datos.
"""

from .database import get_database_manager, DatabaseManager
from .models import (
    Base,
    Article,
    ArticleMetrics,
    Source,
    ScoreLog,
    SystemConfig,
    create_all_tables,
    get_model_info,
)


def initialize_database():
    """Inicializa la base de datos creando tablas si es necesario."""
    db_manager = get_database_manager()
    return db_manager


def get_database_health():
    """Obtiene estadísticas de salud de la base de datos."""
    db_manager = get_database_manager()
    return db_manager.get_health_status()


__all__ = [
    "get_database_manager",
    "DatabaseManager",
    "Base",
    "Article",
    "ArticleMetrics",
    "Source",
    "ScoreLog",
    "SystemConfig",
    "create_all_tables",
    "get_model_info",
    "initialize_database",
    "get_database_health",
]
