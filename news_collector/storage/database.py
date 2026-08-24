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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from news_collector.config.settings import get_runtime_config
from news_collector.contracts import CollectorArticleModel, ScoringRequestModel
from news_collector.utils.logger import get_logger

from .analytics_repository import AnalyticsRepository
from .article_repository import ArticleCursor, ArticlePage, ArticleRepository
from .lifecycle_repository import LifecycleRepository, map_legacy_audit_outcome
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

    .. attribute:: lifecycle
       :type: LifecycleRepository

       Typed read/write access to the Plan 060 / Phase 3a durable lineage
       tables (``publication_attempts``, ``editorial_decisions``, and
       read-only access to the not-yet-populated ``workflow_runs`` /
       ``workflow_stage_attempts`` / ``publication_events``). New code
       reading or writing these tables should call ``db.lifecycle`` directly
       — no ``DatabaseManager``-delegate mirror is added for it (see the
       "New code should call the repositories directly" note below; that
       legacy delegate-mirroring pattern is exactly what is being phased
       out, not extended to new tables).
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
        # Plan 060 / Phase 3b: no delegate-mirror on DatabaseManager (see the
        # attribute docstring above) — call db.lifecycle.* directly.
        self.lifecycle = LifecycleRepository(self)

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
                    # Plan 060 / Fase 3a: sin este pragma SQLite ignora
                    # silenciosamente toda acción de FK, incluido el
                    # ondelete="RESTRICT" de las nuevas tablas de linaje
                    # (workflow_runs, workflow_stage_attempts,
                    # editorial_decisions, publication_attempts,
                    # publication_events) — sin el pragma esas
                    # restricciones no protegerían nada. Es un cambio
                    # global (afecta también los FKs preexistentes, p.ej.
                    # ArticleMetrics.article_id), pero la suite completa
                    # se corrió con esto activado antes de habilitarlo y
                    # nada dependía de que las violaciones de FK se
                    # ignoraran en silencio. No afecta a Alembic: env.py
                    # construye su propio engine (engine_from_config) y
                    # nunca pasa por este listener.
                    cursor.execute("PRAGMA foreign_keys=ON")
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

    def mark_article_published(
        self, article_id: int, pr_url: str, refinery_id: str | None = None
    ) -> bool:
        result = self.articles.mark_article_published(article_id, pr_url, refinery_id)
        # Plan 060 / Phase 3c: dual-write into publication_attempts. Gated on
        # the legacy write's own return value — a False result means the
        # article row doesn't exist, and publication_attempts.article_id is
        # an FK (ondelete="RESTRICT") that would reject an orphan row anyway;
        # skipping avoids both the pointless IntegrityError and a lifecycle
        # row for an article the legacy path deliberately skipped.
        if result:
            self._dual_write_pr_created(article_id, pr_url, refinery_id)
        return result

    def _dual_write_pr_created(
        self, article_id: int, pr_url: str, refinery_id: str | None
    ) -> None:
        """Best-effort: CAS the latest PUBLISHING row to PR_CREATED, or
        insert a fresh PR_CREATED row if none is found / the CAS misses.

        Never raises — a LifecycleRepository failure is logged and
        swallowed so the (already-committed) legacy write remains the
        source of truth.
        """
        resolved_refinery_id = refinery_id or str(article_id)
        try:
            attempts = self.lifecycle.get_publication_attempts_for_article(article_id)
            publishing_attempts = [a for a in attempts if a.state == "PUBLISHING"]
            transitioned = False
            if publishing_attempts:
                # Tie-break by (attempt_number, id): record_publication_attempt's
                # default numbering is COUNT(*) + 1, not MAX(attempt_number) + 1,
                # and there is no unique constraint on (article_id,
                # attempt_number) — id (autoincrement) makes "latest" deterministic.
                latest = max(
                    publishing_attempts, key=lambda a: (a.attempt_number, a.id)
                )
                transitioned = self.lifecycle.transition_publication_attempt(
                    latest.id,
                    from_state="PUBLISHING",
                    to_state="PR_CREATED",
                    pr_url=pr_url,
                    # Defensive self-correction, not required by today's
                    # traced refinery_id invariant — see spec.md recon.
                    refinery_id=resolved_refinery_id,
                )
            if not transitioned:
                # No PUBLISHING row (defensive hasattr callers can skip
                # mark_article_publishing) or a CAS miss (race, or already
                # transitioned) — a PR-created event must still be
                # represented by some row.
                self.lifecycle.record_publication_attempt(
                    article_id,
                    refinery_id=resolved_refinery_id,
                    state="PR_CREATED",
                    pr_url=pr_url,
                    started_at=datetime.now(timezone.utc),
                )
        except Exception:
            logger.exception(
                "Dual-write to publication_attempts failed for article {} "
                "(state=PR_CREATED); legacy write already succeeded and is "
                "unaffected.",
                article_id,
            )

    def reject_publication_attempts(
        self, refinery_ids: list[str], reason: str = ""
    ) -> int:
        transitioned: list[tuple[int, str]] = []
        updated = self.articles.reject_publication_attempts(
            refinery_ids,
            reason,
            on_transition=lambda article_id, refinery_id: transitioned.append(
                (article_id, refinery_id)
            ),
        )
        # Dual-write happens after reject_publication_attempts' own session
        # has committed (on_transition only collected pairs above, it never
        # touched the DB) — never opens a second session against the same
        # SQLite file while the legacy transaction is still in flight.
        for article_id, refinery_id in transitioned:
            self._dual_write_transition(article_id, refinery_id, "REJECTED")
        return updated

    def complete_publication_attempts(
        self, refinery_ids: list[str], deploy_url: str | None
    ) -> int:
        transitioned: list[tuple[int, str]] = []
        updated = self.articles.complete_publication_attempts(
            refinery_ids,
            deploy_url,
            on_transition=lambda article_id, refinery_id: transitioned.append(
                (article_id, refinery_id)
            ),
        )
        for article_id, refinery_id in transitioned:
            self._dual_write_transition(article_id, refinery_id, "COMPLETED")
        return updated

    def _dual_write_transition(
        self, article_id: int, refinery_id: str, to_state: str
    ) -> None:
        """Best-effort: look up the article's latest publication_attempts
        row for ``refinery_id``, read its actual current state (never
        assume ``PR_CREATED`` — a webhook can race ahead of
        ``mark_article_published``'s own fallback insert), and CAS it to
        ``to_state``. Never raises.
        """
        try:
            attempts = self.lifecycle.get_publication_attempts_for_article(article_id)
            matches = [a for a in attempts if a.refinery_id == refinery_id]
            if not matches:
                logger.warning(
                    "Dual-write skipped for article {} (refinery_id={}, "
                    "to_state={}): no publication_attempts row found.",
                    article_id,
                    refinery_id,
                    to_state,
                )
                return
            latest = max(matches, key=lambda a: (a.attempt_number, a.id))
            transitioned = self.lifecycle.transition_publication_attempt(
                latest.id,
                from_state=latest.state,
                to_state=to_state,
            )
            if not transitioned:
                logger.warning(
                    "Dual-write CAS miss for article {} (refinery_id={}, "
                    "attempt_id={}, from_state={}, to_state={}).",
                    article_id,
                    refinery_id,
                    latest.id,
                    latest.state,
                    to_state,
                )
        except Exception:
            logger.exception(
                "Dual-write transition failed for article {} (refinery_id={}, "
                "to_state={}); legacy transition already succeeded and is "
                "unaffected.",
                article_id,
                refinery_id,
                to_state,
            )

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
        result = self.articles.update_article_audit_status(
            article_id,
            audit_status,
            reason,
            attempts=attempts,
            timeout_seconds=timeout_seconds,
            model=model,
            endpoint=endpoint,
        )
        if result:
            self._dual_write_audit_decision(
                article_id,
                audit_status,
                reason,
                attempts=attempts,
                timeout_seconds=timeout_seconds,
                model=model,
                endpoint=endpoint,
            )
        return result

    def _dual_write_audit_decision(
        self,
        article_id: int,
        audit_status: str,
        reason: str,
        *,
        attempts: int | None,
        timeout_seconds: int | None,
        model: str | None,
        endpoint: str | None,
    ) -> None:
        """Best-effort: record an editorial_decisions row for a terminal
        audit outcome. No-ops for non-terminal states (audit_pending,
        audit_skipped*, unrecognized), matching the Phase 3b backfill's
        rule exactly. Never raises.
        """
        mapped = map_legacy_audit_outcome(audit_status)
        if mapped is None:
            return
        details: Dict[str, Any] = {"legacy_state": audit_status}
        if attempts is not None:
            details["attempts"] = attempts
        if timeout_seconds is not None:
            details["timeout_seconds"] = timeout_seconds
        if model:
            details["model"] = model
        if endpoint:
            details["endpoint"] = endpoint
        try:
            self.lifecycle.record_editorial_decision(
                article_id=article_id,
                decision_type="auditor",
                outcome=mapped,
                reason=reason or None,
                decided_at=datetime.now(timezone.utc),
                details=details,
            )
        except Exception:
            logger.exception(
                "Dual-write to editorial_decisions failed for article {} "
                "(audit_status={}); legacy write already succeeded and is "
                "unaffected.",
                article_id,
                audit_status,
            )

    def is_article_published(self, article_id: int) -> bool:
        return self.articles.is_article_published(article_id)

    def is_article_in_flight_or_done(self, article_id: int) -> bool:
        return self.articles.is_article_in_flight_or_done(article_id)

    def articles_in_flight_or_done(self, article_ids: list[int]) -> set[int]:
        return self.articles.articles_in_flight_or_done(article_ids)

    def published_ids_in(self, article_ids: list[int]) -> set[int]:
        return self.articles.published_ids_in(article_ids)

    def mark_article_publishing(self, article_id: int, branch_name: str) -> bool:
        result = self.articles.mark_article_publishing(article_id, branch_name)
        # Plan 060 / Phase 3c: dual-write into publication_attempts. Gated
        # on the legacy write's own return value — see mark_article_published
        # above for why (FK ondelete="RESTRICT" on an article row that
        # doesn't exist).
        if result:
            try:
                self.lifecycle.record_publication_attempt(
                    article_id,
                    refinery_id=str(article_id),
                    state="PUBLISHING",
                    started_at=datetime.now(timezone.utc),
                    branch_name=branch_name,
                )
            except Exception:
                logger.exception(
                    "Dual-write to publication_attempts failed for article "
                    "{} (state=PUBLISHING); legacy write already succeeded "
                    "and is unaffected.",
                    article_id,
                )
        return result

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
        max_age_days: Optional[int] = None,
    ) -> List[Article]:
        return self.articles.get_articles_by_score(
            limit, min_score, exclude_published, max_age_days
        )

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

    def get_pending_articles_page(
        self,
        limit: int,
        status: str = PENDING_STATUS,
        cursor: Optional[ArticleCursor] = None,
    ) -> ArticlePage:
        return self.articles.get_pending_articles_page(limit, status, cursor)

    def get_completed_articles_for_rescoring_page(
        self,
        limit: int,
        days_back: int = 14,
        cursor: Optional[ArticleCursor] = None,
    ) -> ArticlePage:
        return self.articles.get_completed_articles_for_rescoring_page(
            limit, days_back, cursor
        )

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

    def reset_article_for_reprocess(self, article_id: int) -> bool:
        return self.articles.reset_article_for_reprocess(article_id)

    def clear_all_articles(self) -> int:
        return self.articles.clear_all_articles()

    # ---- Source delegates ----

    def get_source_circuit_state(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self.sources.get_source_circuit_state(source_id)

    def set_source_active(self, source_id: str, active: bool) -> bool:
        return self.sources.set_source_active(source_id, active)

    def delete_source(self, source_id: str) -> bool:
        return self.sources.delete_source(source_id)

    def upsert_source(self, source_id: str, source_config: Dict[str, Any]) -> bool:
        return self.sources.upsert_source(source_id, source_config)

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
