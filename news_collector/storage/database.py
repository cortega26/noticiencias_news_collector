# src/storage/database.py
# Manejador de base de datos para News Collector System
# ====================================================

"""
Module role: Manages database connections and connection pooling, acting as
a backward-compatible facade over focused repositories.

All CRUD operations are delegated to one of three repositories:

- ``db.articles`` — :class:`~news_collector.storage.article_repository.ArticleRepository`
- ``db.sources``  — :class:`~news_collector.storage.source_repository.SourceRepository`
- ``db.analytics`` — :class:`~news_collector.storage.analytics_repository.AnalyticsRepository`

The 30+ public methods on :class:`DatabaseManager` remain available unchanged
so that existing callers require no import changes.

Inputs:
- Database configuration dictionaries (URL, type, pool settings).
- Validated ``CollectorArticleModel`` instances or compatible dictionaries for saving articles.
- Source IDs and states for circuit breaker updates.

Outputs:
- SQLAlchemy ``Article`` models representing persisted data.
- Boolean flags indicating successful saves, existence checks, or canonical slug assignments.
- Dictionaries describing source circuit breaker states.

Side effects:
- Writes and upserts data to the configured SQL database.
- Updates circuit breaker tracking states for collection sources.
- Generates and persists simhash/clustering metadata for duplicate detection.

Invariants:
- Canonical identity (slugs) persists immutably and cannot be overwritten once set (``set_canonical_slug``).
- Gracefully ignores duplicate inserts using UPSERT/existence-check logic instead of crashing on ``IntegrityError``.

Failure modes:
- SQLAlchemy exceptions (e.g., ``IntegrityError``) are caught, rolled back, and typically return ``None``.
- Raises ``ValueError`` if an invalid ``CollectorArticleModel`` payload is passed to the save operations.
"""

import contextlib
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from news_collector.config.settings import get_runtime_config
from news_collector.contracts import CollectorArticleModel, ScoringRequestModel
from news_collector.utils.logger import get_logger

from .analytics_repository import AnalyticsRepository
from .article_repository import ArticleRepository
from .models import PENDING_STATUS, Article
from .source_repository import SourceRepository

# Configurar logging para este módulo
logger = get_logger().create_module_logger(__name__)


def build_database_url(config: Dict[str, Any]) -> Union[str, URL]:
    """Build the SQLAlchemy URL for a database config, with no side effects.

    Shared by :class:`DatabaseManager` (which then opens the connection and
    creates tables) and the read-only migration guard
    (:mod:`news_collector.storage.migration_guard`), which must never create
    tables — keeping URL construction in one place stops the two from
    silently drifting onto different connection targets.
    """
    if config["type"] == "sqlite":
        return f"sqlite:///{config['path']}"
    elif config["type"] == "postgresql":
        query_params: Dict[str, Any] = {}
        ssl_mode = config.get("sslmode")
        if ssl_mode:
            query_params["sslmode"] = ssl_mode

        return URL.create(
            "postgresql",
            username=config.get("user"),
            password=config.get("password") or None,
            host=config.get("host"),
            port=int(config.get("port", 5432)),
            database=config.get("name"),
            query=query_params,
        )
    else:
        raise ValueError(f"Tipo de base de datos no soportado: {config['type']}")


class DatabaseManager:
    """
    Clase principal que maneja todas las operaciones de base de datos.

    Piensa en esta clase como un superintendente de biblioteca que conoce
    cada rincón del edificio y puede ayudarte a encontrar cualquier
    información instantáneamente, o guardarte nuevos materiales en el
    lugar más apropiado.

    Estrategia de migración
    -----------------------
    La inicialización hace únicamente dos cosas:

    1. Construye el engine con la configuración de pooling y timeouts
       adecuada para el backend seleccionado (incluyendo PostgreSQL en
       producción).
    2. Ejecuta `Base.metadata.create_all` para crear tablas que no
       existan todavía (conveniencia de desarrollo/tests; no aplica
       cambios a tablas ya existentes).

    Alembic es la única autoridad de cambios de esquema (columnas nuevas,
    índices, backfills). Esta clase nunca los aplica — deben correrse
    explícitamente vía ``scripts/migrate.py`` / ``alembic upgrade head``
    antes de que un consumidor nuevo dependa de ellos. Ver
    ``docs/database_deployment.md`` y
    ``news_collector.storage.migration_guard`` para la verificación
    read-only de que el esquema aplicado coincide con el head empaquetado.

    .. attribute:: articles
       :type: ArticleRepository

       Article CRUD, deduplication, clustering, scoring, and publishing state.

    .. attribute:: sources
       :type: SourceRepository

       Source circuit breaker, feed metadata, and initialisation.

    .. attribute:: analytics
       :type: AnalyticsRepository

       Analytics queries, daily stats, maintenance, and health checks.
    """

    def __init__(self, database_config: Optional[Dict[str, Any]] = None):
        """
        Inicializa el manejador de base de datos.

        Args:
            database_config: Configuración de base de datos. Si no se proporciona,
                           usa la configuración actual de get_runtime_config().

        Nota: el engine/pool se construye una sola vez aquí. Un cambio de
        driver/host/credenciales posterior vía refresh_runtime_config() queda
        marcado restart_required en el snapshot — esta instancia (singleton
        vía get_database_manager()) no se reconstruye sola.
        """
        self.config = database_config or get_runtime_config().database_config
        self.engine = None
        self.SessionLocal = None
        self._setup_database()

        # Focused repositories — the actual implementation lives here.
        self.articles = ArticleRepository(self)
        self.sources = SourceRepository(self)
        self.analytics = AnalyticsRepository(self)

    def _setup_database(self):
        """
        Configura la conexión a la base de datos.

        Este método es como preparar el edificio de la biblioteca:
        verificar que las puertas funcionen, que haya luz, y que
        todos los sistemas estén operativos.
        """
        try:
            if self.config["type"] == "sqlite":
                # Para SQLite, creamos el archivo si no existe
                db_path = self.config["path"]
                db_path.parent.mkdir(parents=True, exist_ok=True)
                database_url = build_database_url(self.config)

                # SQLite con configuraciones optimizadas
                self.engine = create_engine(
                    database_url,
                    echo=False,  # Cambiar a True para ver todas las consultas SQL
                    connect_args={
                        "check_same_thread": False,  # Necesario para SQLite con threads
                        "timeout": 30,  # Aumentado a 30s para concurrencia async
                    },
                    pool_pre_ping=True,
                )

                # Habilitar WAL mode para mejorar concurrencia
                from sqlalchemy import event

                @event.listens_for(self.engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.close()

            elif self.config["type"] == "postgresql":
                database_url = build_database_url(self.config)

                connect_args: Dict[str, Any] = {
                    "connect_timeout": int(self.config.get("connect_timeout", 10))
                }
                statement_timeout = int(self.config.get("statement_timeout", 0))
                if statement_timeout > 0:
                    connect_args["options"] = (
                        f"-c statement_timeout={statement_timeout}"
                    )

                self.engine = create_engine(
                    database_url,
                    echo=False,
                    poolclass=QueuePool,
                    pool_size=int(self.config.get("pool_size", 10)),
                    max_overflow=int(self.config.get("max_overflow", 5)),
                    pool_timeout=int(self.config.get("pool_timeout", 30)),
                    pool_recycle=int(self.config.get("pool_recycle", 1800)),
                    pool_pre_ping=True,
                    connect_args=connect_args,
                )

            else:
                raise ValueError(
                    f"Tipo de base de datos no soportado: {self.config['type']}"
                )

            # Crear sesión factory
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine,
                expire_on_commit=False,
            )

            # Crear todas las tablas
            from .models import Base

            Base.metadata.create_all(self.engine)

            # Schema migrations must now be run form external tooling (scripts/migrate.py)
            # self._run_schema_migrations()

            logger.info(
                f"✅ Base de datos configurada exitosamente: {self.config['type']}"
            )

        except Exception as e:
            logger.error(f"❌ Error configurando base de datos: {e}")
            raise

    @contextmanager
    def get_session(self):
        """
        Context manager para manejar sesiones de base de datos de manera segura.

        Esto es como tener un sistema de préstamo de libros que automáticamente
        registra cuando tomas un libro y cuando lo devuelves, asegurándose
        de que cada estantería permanezca en orden.

        Uso:
            with db_manager.get_session() as session:
                # Hacer operaciones con la base de datos
                article = session.query(Article).first()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Error en operación de base de datos: {e}")
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Dispose pooled connections for clean shutdowns/tests."""
        if self.engine is None:
            return
        try:
            try:
                self.engine.dispose(close=True)
            except TypeError:
                self.engine.dispose()
            self.engine = None
            self.SessionLocal = None
        except Exception as exc:  # pragma: no cover - defensive cleanup
            logger.warning("Error cerrando el engine de base de datos: {}", exc)

    def __del__(self) -> None:
        if getattr(self, "engine", None) is None:
            return
        with contextlib.suppress(Exception):
            self.close()

    # =====================================================================
    # Backward-compatible delegates → focused repositories
    # =====================================================================
    #
    # These methods have identical signatures to the pre-refactoring
    # DatabaseManager so that all existing callers continue to work without
    # import changes.  The implementation resides in the repository classes.
    #
    # New code should call the repositories directly:
    #     db.articles.save_article(...)   instead of  db.save_article(...)
    #     db.sources.get_source_circuit_state(...)  instead of  db.get_source_circuit_state(...)
    # =====================================================================

    # ---- Article delegates ----

    def article_exists(self, url: str) -> bool:
        return self.articles.article_exists(url)

    def get_article_by_url(self, url: str) -> Optional[Article]:
        return self.articles.get_article_by_url(url)

    def get_article_by_id(self, article_id: int) -> Optional[Article]:
        return self.articles.get_article_by_id(article_id)

    def articles_exist(self, urls: List[str]) -> Set[str]:
        return self.articles.articles_exist(urls)

    def mark_article_published(self, article_id: int, pr_url: str) -> bool:
        return self.articles.mark_article_published(article_id, pr_url)

    def update_article_audit_status(
        self,
        article_id: int,
        audit_status: str,
        reason: str = "",
        *,
        attempts: int | None = None,
        timeout_seconds: int | None = None,
        model: str | None = None,
        endpoint: str | None = None,
    ) -> bool:
        return self.articles.update_article_audit_status(
            article_id,
            audit_status,
            reason,
            attempts=attempts,
            timeout_seconds=timeout_seconds,
            model=model,
            endpoint=endpoint,
        )

    def is_article_published(self, article_id: int) -> bool:
        return self.articles.is_article_published(article_id)

    def published_ids_in(self, article_ids: list[int]) -> set[int]:
        return self.articles.published_ids_in(article_ids)

    def mark_article_publishing(self, article_id: int, branch_name: str) -> bool:
        return self.articles.mark_article_publishing(article_id, branch_name)

    def get_publishing_state(self, article_id: int) -> dict | None:
        return self.articles.get_publishing_state(article_id)

    def is_processed(self, identifier: str | int) -> bool:
        return self.articles.is_processed(identifier)

    def get_canonical_slug(self, article_id: int | str) -> Optional[str]:
        return self.articles.get_canonical_slug(article_id)

    def set_canonical_slug(self, article_id: int | str, slug: str) -> bool:
        return self.articles.set_canonical_slug(article_id, slug)

    def save_article(
        self, article_data: CollectorArticleModel | Dict[str, Any]
    ) -> Optional[Article]:
        return self.articles.save_article(article_data)

    def save_articles_bulk(
        self,
        articles_data: Sequence[Union[Dict[str, Any], CollectorArticleModel]],
        batch_size: int = 50,
    ) -> int:
        return self.articles.save_articles_bulk(articles_data, batch_size)

    def get_articles_by_score(
        self,
        limit: int = 10,
        min_score: float = 0.0,
        exclude_published: bool = False,
    ) -> List[Article]:
        return self.articles.get_articles_by_score(limit, min_score, exclude_published)

    def get_articles_by_category(
        self, category: str, days_back: int = 7
    ) -> List[Article]:
        return self.articles.get_articles_by_category(category, days_back)

    def get_pending_articles(
        self, limit: Optional[int] = None, status: str = PENDING_STATUS
    ) -> List[Article]:
        return self.articles.get_pending_articles(limit, status)

    def get_completed_articles_for_rescoring(
        self, days_back: int = 14
    ) -> List[Article]:
        return self.articles.get_completed_articles_for_rescoring(days_back)

    def update_validation_status_bulk(self, mappings: List[Dict[str, Any]]) -> bool:
        return self.articles.update_validation_status_bulk(mappings)

    def update_articles_score_bulk(
        self,
        score_data_list: List[Tuple[int, ScoringRequestModel | Dict[str, Any]]],
    ) -> bool:
        return self.articles.update_articles_score_bulk(score_data_list)

    def update_article_score(
        self,
        article_id: int,
        score_data: ScoringRequestModel | Dict[str, Any],
    ) -> bool:
        return self.articles.update_article_score(article_id, score_data)

    def delete_article(self, article_id: Union[int, str]) -> bool:
        return self.articles.delete_article(article_id)

    def clear_all_articles(self) -> int:
        return self.articles.clear_all_articles()

    # ---- Source delegates ----

    def get_source_circuit_state(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.sources.get_source_circuit_state(source_id)

    def update_source_circuit_state(
        self,
        source_id: str,
        success: bool,
        error_message: Optional[str] = None,
        force_cooldown_until: Optional[datetime] = None,
    ) -> None:
        return self.sources.update_source_circuit_state(
            source_id, success, error_message, force_cooldown_until
        )

    def initialize_sources(self, sources_config: Dict[str, Dict]) -> None:
        return self.sources.initialize_sources(sources_config)

    def get_source_feed_metadata(self, source_id: str) -> Dict[str, Optional[str]]:
        return self.sources.get_source_feed_metadata(source_id)

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        return self.sources.update_source_feed_metadata(
            source_id,
            etag=etag,
            last_modified=last_modified,
            content_hash=content_hash,
        )

    def update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        return self.sources.update_source_stats(source_id, stats)

    # ---- Analytics delegates ----

    def get_collection_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        return self.analytics.get_collection_stats(days)

    def get_source_performance(self) -> List[Dict[str, Any]]:
        return self.analytics.get_source_performance()

    def get_category_breakdown(self) -> List[Dict[str, Any]]:
        return self.analytics.get_category_breakdown()

    def get_score_distribution(self, buckets: int = 10) -> Dict[str, int]:
        return self.analytics.get_score_distribution(buckets)

    def get_daily_stats(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        return self.analytics.get_daily_stats(date)

    def get_top_sources_performance(self, days_back: int = 30) -> List[Dict[str, Any]]:
        return self.analytics.get_top_sources_performance(days_back)

    def cleanup_old_data(self, days_to_keep: int = 90) -> Dict[str, Any]:
        return self.analytics.cleanup_old_data(days_to_keep)

    def get_health_status(self) -> Dict[str, Any]:
        return self.analytics.get_health_status()


# Instancia global del manejador de base de datos
# ===============================================
# Esta será nuestra conexión principal que usarán todos los demás módulos

_db_manager = None


def get_database_manager() -> DatabaseManager:
    """
    Función factory para obtener la instancia del DatabaseManager.

    Esto implementa el patrón Singleton, asegurándonos de que solo
    exista una conexión a la base de datos en toda la plataforma.
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    elif _db_manager.SessionLocal is None:
        # Instance exists but was closed (zombie). Re-initialize.
        logger.warning("♻️ Detectada instancia de DB cerrada. Reinicializando...")
        _db_manager = DatabaseManager()
    return _db_manager
