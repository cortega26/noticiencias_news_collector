# src/storage/database.py
# Manejador de base de datos para News Collector System
# ====================================================

"""
Module role: Manages database connections, connection pooling, and CRUD operations for articles and sources, abstracting SQLite and PostgreSQL backends.

Inputs:
- Database configuration dictionaries (URL, type, pool settings).
- Validated `CollectorArticleModel` instances or compatible dictionaries for saving articles.
- Source IDs and states for circuit breaker updates.

Outputs:
- SQLAlchemy `Article` models representing persisted data.
- Boolean flags indicating successful saves, existence checks, or canonical slug assignments.
- Dictionaries describing source circuit breaker states.

Side effects:
- Writes and upserts data to the configured SQL database.
- Updates circuit breaker tracking states for collection sources.
- Generates and persists simhash/clustering metadata for duplicate detection.

Invariants:
- Canonical identity (slugs) persists immutably and cannot be overwritten once set (`set_canonical_slug`).
- Gracefully ignores duplicate inserts using UPSERT/existence-check logic instead of crashing on `IntegrityError`.

Failure modes:
- SQLAlchemy exceptions (e.g., `IntegrityError`) are caught, rolled back, and typically return `None`.
- Raises `ValueError` if an invalid `CollectorArticleModel` payload is passed to the save operations.
"""

import contextlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

from sqlalchemy import create_engine, desc
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only, sessionmaker
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.pool import QueuePool

from news_collector.utils.pydantic_compat import get_pydantic_module

ValidationError = get_pydantic_module().ValidationError

import logging

from news_collector.config.settings import (
    COLLECTION_CONFIG,
    DATABASE_CONFIG,
    DEDUP_CONFIG,
)
from news_collector.contracts import CollectorArticleModel, ScoringRequestModel

from ..storage.analytics import (
    category_breakdown,
    collection_stats,
    daily_stats,
    score_distribution,
    source_performance,
    top_sources_performance,
)
from ..storage.maintenance import cleanup_old_data, health_status
from ..storage.models import PENDING_STATUS, Article, Base, ScoreLog, Source
from ..utils.dedupe import (
    duplication_confidence,
    generate_cluster_id,
    hamming_distance,
    normalize_article_text,
    sha256_hex,
    simhash64,
)
from ..utils.url_canonicalizer import canonicalize_url

# Configurar logging para este módulo
logger = logging.getLogger(__name__)

SIMHASH_BITS = 64
SIMHASH_MASK = (1 << SIMHASH_BITS) - 1
SIMHASH_SIGN_BIT = 1 << (SIMHASH_BITS - 1)


class DatabaseManager:
    """
    Clase principal que maneja todas las operaciones de base de datos.

    Piensa en esta clase como un superintendente de biblioteca que conoce
    cada rincón del edificio y puede ayudarte a encontrar cualquier
    información instantáneamente, o guardarte nuevos materiales en el
    lugar más apropiado.

    Estrategia de migración
    -----------------------
    La inicialización ejecuta automáticamente una secuencia segura para
    mantener el esquema alineado con el código:

    1. Construye el engine con la configuración de pooling y timeouts
       adecuada para el backend seleccionado (incluyendo PostgreSQL en
       producción).
    2. Ejecuta `Base.metadata.create_all` para crear tablas que no
       existan todavía.
    3. Corre ``_run_schema_migrations`` que aplica ajustes idempotentes
       documentados en ``docs/database_deployment.md``.

    Antes de un despliegue productivo se debe revisar la guía de
    despliegue para completar los pasos manuales como verificación de
    backups y replicación.
    """

    def __init__(self, database_config: Optional[Dict[str, Any]] = None):
        """
        Inicializa el manejador de base de datos.

        Args:
            database_config: Configuración de base de datos. Si no se proporciona,
                           usa la configuración por defecto de settings.py
        """
        self.config = database_config or DATABASE_CONFIG
        self.engine = None
        self.SessionLocal = None
        self.simhash_threshold = DEDUP_CONFIG.get("simhash_threshold", 10)
        self.simhash_candidate_window = DEDUP_CONFIG.get(
            "simhash_candidate_window", 500
        )
        self._setup_database()

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
                database_url = f"sqlite:///{db_path}"

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
                query_params: Dict[str, Any] = {}
                ssl_mode = self.config.get("sslmode")
                if ssl_mode:
                    query_params["sslmode"] = ssl_mode

                database_url = URL.create(
                    "postgresql",
                    username=self.config.get("user"),
                    password=self.config.get("password") or None,
                    host=self.config.get("host"),
                    port=int(self.config.get("port", 5432)),
                    database=self.config.get("name"),
                    query=query_params,
                )

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
            logger.warning("Error cerrando el engine de base de datos: %s", exc)

    def __del__(self) -> None:
        if getattr(self, "engine", None) is None:
            return
        with contextlib.suppress(Exception):
            self.close()
            # During shutdown, logging/sys might be gone or fragile.
            # We suppress errors to avoid annoying "NoneType" tracebacks.

    def get_source_circuit_state(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves circuit breaker state for a source.
        """
        with self.get_session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return None
            return {
                "status": source.status,
                "next_retry_at": source.next_retry_at,
                "consecutive_failures": source.consecutive_failures,
                "is_active": source.is_active,
                "last_checked": source.last_checked,
            }

    def update_source_circuit_state(
        self,
        source_id: str,
        success: bool,
        error_message: Optional[str] = None,
        force_cooldown_until: Optional[datetime] = None,
    ) -> None:
        """
        Updates the circuit breaker state for a source.
        Implements the logic: 3 strikes -> COOLDOWN (4 hours).
        Allows forcing COOLDOWN immediately (e.g. for 429s).
        """
        with self.get_session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return

            if success:
                # Reset on success
                if source.consecutive_failures > 0 or source.status != "ACTIVE":
                    source.consecutive_failures = 0
                    source.status = "ACTIVE"
                    source.next_retry_at = None
                    source.error_message = (
                        None  # Clear error on success? Or keep history?
                    )
                    # We usually keep history in logs, but clearing current error state is good.
                    logger.info(
                        f"✅ Source {source_id} recovered/healthy. Reset circuit."
                    )
            else:
                # Handle Failure
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                source.error_message = (
                    str(error_message)[:500] if error_message else "Unknown Error"
                )

                # Check Threshold (Configurable)
                max_failures = COLLECTION_CONFIG.get("circuit_breaker_max_failures", 3)
                cooldown_hours = COLLECTION_CONFIG.get(
                    "circuit_breaker_cooldown_hours", 4
                )

                if force_cooldown_until:
                    # Explicit backoff (e.g. 429)
                    source.status = "COOLDOWN"
                    source.next_retry_at = force_cooldown_until
                    logger.warning(
                        f"🔌 CIRCUIT BREAKER FORCED: Source {source_id} entering COOLDOWN until {source.next_retry_at} (Reason: {error_message})"
                    )
                elif source.consecutive_failures >= max_failures:
                    # Enter Cooldown
                    source.status = "COOLDOWN"
                    source.next_retry_at = datetime.now(timezone.utc) + timedelta(
                        hours=cooldown_hours
                    )
                    logger.warning(
                        f"🔌 CIRCUIT BREAKER TRIPPED: Source {source_id} entering COOLDOWN until {source.next_retry_at}"
                    )

            session.add(source)

    # =====================================
    # Operaciones Principales (Public API)
    # =====================================

    def article_exists(self, url: str) -> bool:
        """
        Check if an article with the given URL already exists in the database.
        Efficient query using exists().

        Defense-in-depth: canonicalizes the URL before querying (LAW-4).
        """
        url = canonicalize_url(url) or url
        with self.get_session() as session:
            result = session.query(
                session.query(Article).filter_by(url=url).exists()
            ).scalar()
            return bool(result)

    def articles_exist(self, urls: List[str]) -> Set[str]:
        """
        Batch check for existing articles by URL.
        Returns a set of URLs that already exist.

        Defense-in-depth: canonicalizes all URLs before querying (LAW-4).
        """
        if not urls:
            return set()

        urls = [canonicalize_url(u) or u for u in urls]

        # Split into chunks to avoid SQLite limits if necessary (999 variables)
        # SQLAlchemy usually handles IN clauses well, but safe chunking is better.
        CHUNK_SIZE = 500
        existing_urls: Set[str] = set()

        with self.get_session() as session:
            for i in range(0, len(urls), CHUNK_SIZE):
                chunk = urls[i : i + CHUNK_SIZE]
                results = (
                    session.query(Article.url).filter(Article.url.in_(chunk)).all()
                )
                existing_urls.update(r[0] for r in results)

        return existing_urls

    def mark_article_published(self, article_id: int, pr_url: str) -> bool:
        """
        Records publication candidate state after PR creation.
        This backend stage is PR_CREATED (candidate), not final website publication.
        """
        with self.get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                logger.warning(
                    f"Could not find article {article_id} to mark as published."
                )
                return False

            article.processing_status = "completed"
            article.published_at = datetime.now(timezone.utc)
            article.published_url = pr_url
            article_metadata = dict(article.article_metadata or {})
            publication_meta = dict(article_metadata.get("publication") or {})
            publication_meta.update(
                {
                    "state": "PR_CREATED",
                    "pr_url": pr_url,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            article_metadata["publication"] = publication_meta
            article.article_metadata = article_metadata
            # We don't change 'published_date' (original source date), only 'published_at' (our publish date).

            session.add(article)
            logger.info(f"Marked article {article_id} as PR_CREATED (PR: {pr_url})")
            return True

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
        """
        Persists auditor execution outcome without mutating publication stage.
        """
        with self.get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                logger.warning(
                    "Could not find article %s to update audit status.", article_id
                )
                return False

            article_metadata = dict(article.article_metadata or {})
            audit_meta = dict(article_metadata.get("audit") or {})
            audit_meta.update(
                {
                    "state": str(audit_status),
                    "reason": str(reason or ""),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if attempts is not None:
                audit_meta["attempts"] = int(attempts)
            if timeout_seconds is not None:
                audit_meta["timeout_seconds"] = int(timeout_seconds)
            if model:
                audit_meta["model"] = str(model)
            if endpoint:
                audit_meta["endpoint"] = str(endpoint)

            article_metadata["audit"] = audit_meta
            article.article_metadata = article_metadata
            session.add(article)
            logger.info(
                "Updated audit state for article %s: %s", article_id, audit_status
            )
            return True

    def is_article_published(self, article_id: int) -> bool:
        """
        Checks if an article has already reached PR_CREATED state.
        """
        with self.get_session() as session:
            # We check for ID existence and status
            stmt = session.query(Article).filter(Article.id == article_id)
            article = stmt.first()
            if not article:
                return False

            return article.published_url is not None or article.published_at is not None

    def is_processed(self, identifier: str | int) -> bool:
        """
        Backwards-compatible helper used by Refinery for file-based workflows.
        Returns True only if the identifier maps to a numeric article ID that
        has already been published.
        """
        ident_str = str(identifier).strip()
        if ident_str.isdigit():
            return self.is_article_published(int(ident_str))

        stem = ident_str.rsplit(".", 1)[0]
        if stem.isdigit():
            return self.is_article_published(int(stem))

        return False

    def get_canonical_slug(self, article_id: int | str) -> Optional[str]:
        """
        Retrieves the immutable canonical slug for an article.
        Ensures URL stability across multiple processing runs.
        """
        try:
            val_id = int(str(article_id).strip())
        except ValueError:
            return None

        with self.get_session() as session:
            article = session.query(Article).filter(Article.id == val_id).first()
            if article:
                return str(article.canonical_slug) if article.canonical_slug else None
        return None

    def set_canonical_slug(self, article_id: int | str, slug: str) -> bool:
        """
        Persists the immutable canonical slug for an article.
        Fails safely if already set (though logic should handle this upstream).
        """
        try:
            val_id = int(str(article_id).strip())
        except ValueError:
            return False

        if not slug or not slug.strip():
            return False

        with self.get_session() as session:
            article = session.query(Article).filter(Article.id == val_id).first()
            if not article:
                return False

            # Double check to respect immutability
            if article.canonical_slug and article.canonical_slug != slug:
                logger.warning(
                    f"Attempted to overwrite existing slug {article.canonical_slug} with {slug}. Ignored."
                )
                return False

            article.canonical_slug = slug
            session.add(article)
            return True

    # OPERACIONES CON ARTÍCULOS
    # =====================================

    def save_article(  # noqa: C901
        self, article_data: CollectorArticleModel | Dict[str, Any]
    ) -> Optional[Article]:
        """
        Guarda un nuevo artículo en la base de datos.

        Esta función es como tener un bibliotecario que verifica que no
        tengas ya el mismo libro antes de agregarlo a la colección,
        y que lo catalogue apropiadamente.

        Args:
            article_data: Instancia validada del contrato del colector o un
                diccionario compatible con el esquema.

        Returns:
            El artículo guardado o None si ya existía
        """
        if isinstance(article_data, CollectorArticleModel):
            model = article_data
        else:
            try:
                model = CollectorArticleModel.model_validate(article_data)
            except ValidationError as exc:
                raise ValueError(f"Invalid collector payload: {exc}") from exc

        payload = model.model_dump_for_storage()
        normalized_published = self._ensure_timezone(payload.get("published_date"))
        if normalized_published:
            payload["published_date"] = normalized_published

        with self.get_session() as session:
            try:
                # Verificar si ya existe por URL
                existing: Article | None = (
                    session.query(Article).filter_by(url=payload["url"]).first()
                )
                if existing:
                    logger.warning(
                        f"🔍 [DEBUG] Found existing article by URL: {payload['url']} (ID: {existing.id})"
                    )
                    # HEALING LOGIC: If existing content is missing/short but we found better content, update it.
                    new_content = payload.get("content")
                    old_content = existing.content

                    new_len = len(new_content) if new_content else 0
                    old_len = len(old_content) if old_content else 0
                    logger.warning(
                        f"📏 [DEBUG] Content lengths - New: {new_len}, Old: {old_len}"
                    )

                    if new_content and len(new_content) > 1000:
                        if not old_content or len(old_content) < 1000:
                            logger.warning(
                                f"✨ [HEALING] Upgrading article {existing.id} content ({old_len} -> {new_len})"
                            )
                            existing.content = new_content
                            # Update summary too if needed
                            existing_record = cast(Any, existing)
                            existing_record.summary = payload.get("summary")
                            session.add(existing)
                            session.flush()
                            return existing
                        else:
                            logger.warning(
                                f"🚫 [DEBUG] Old content sufficient ({old_len} >= 1000)"
                            )
                    else:
                        logger.warning(
                            f"🚫 [DEBUG] New content too short ({new_len} <= 1000)"
                        )

                    logger.debug(f"Artículo ya existe: {payload['url']}")
                    return None

                norm_title, norm_summary, normalized_text = normalize_article_text(
                    payload.get("title", ""),
                    payload.get("summary", ""),
                )
                normalized_basis = normalized_text or payload["url"]
                content_hash = sha256_hex(normalized_basis)

                # Verificar duplicados exactos por hash
                existing_by_content = (
                    session.query(Article).filter_by(content_hash=content_hash).first()
                )
                if existing_by_content:
                    logger.debug(
                        f"Contenido duplicado encontrado para: {payload['title']}"
                    )
                    return None

                simhash_value = self._simhash_normalize_unsigned(
                    simhash64(normalized_basis)
                )
                simhash_prefix = self._simhash_prefix_value(simhash_value)
                cluster_id, confidence = self._assign_cluster(
                    session,
                    int(simhash_value) if simhash_value is not None else 0,
                    payload.get("published_date"),
                )

                article_metadata = payload.get("article_metadata", {}) or {}
                article_metadata.setdefault("normalized_title", norm_title)
                article_metadata.setdefault("normalized_summary", norm_summary)
                article_metadata.setdefault(
                    "original_url",
                    payload.get("original_url", payload["url"]),
                )

                # Use override status if provided (e.g. for rejected candidates), otherwise pending.
                initial_status = (
                    getattr(model, "processing_status_override", None) or PENDING_STATUS
                )

                # Crear nuevo artículo
                article = Article(
                    url=payload["url"],
                    content_hash=content_hash,
                    simhash=self._simhash_to_storage(simhash_value),
                    simhash_prefix=simhash_prefix,
                    title=payload["title"],
                    summary=payload.get("summary"),
                    content=payload.get("content"),
                    source_id=payload["source_id"],
                    source_name=payload["source_name"],
                    published_date=payload.get("published_date"),
                    published_tz_offset_minutes=payload.get(
                        "published_tz_offset_minutes"
                    ),
                    published_tz_name=payload.get("published_tz_name"),
                    authors=payload.get("authors"),
                    category=payload["category"],
                    doi=payload.get("doi"),
                    journal=payload.get("journal"),
                    is_preprint=payload.get("is_preprint", False),
                    language=payload.get("language", "en"),
                    processing_status=initial_status,
                    article_metadata=article_metadata,
                    word_count=payload.get("word_count"),
                    reading_time_minutes=payload.get("reading_time_minutes"),
                    cluster_id=cluster_id,
                    duplication_confidence=confidence,
                )

                session.add(article)
                session.flush()  # Para obtener el ID sin hacer commit

                # Revalidar cluster para evitar outliers
                if cluster_id:
                    self._revalidate_cluster(session, cluster_id)

                logger.info(f"✅ Artículo guardado: {article.title[:50]}...")
                return article

            except IntegrityError as e:
                session.rollback()
                logger.warning(f"Intento de guardar artículo duplicado: {e}")
                return None
            except Exception as e:
                logger.error(f"Error guardando artículo: {e}")
                raise

    def save_articles_bulk(  # noqa: C901
        self,
        articles_data: Sequence[Union[Dict[str, Any], CollectorArticleModel]],
        batch_size: int = 50,
    ) -> int:
        """
        Guarda múltiples artículos de manera eficiente y en lotes para evitar bloqueos largos.
        """
        if not articles_data:
            return 0

        saved_count = 0
        batch_count = 0
        seen_urls = set()

        with self.get_session() as session:
            try:
                for data in articles_data:
                    # ... processing code ...
                    if isinstance(data, CollectorArticleModel):
                        model = data
                    else:
                        try:
                            model = CollectorArticleModel.model_validate(data)
                        except ValidationError as exc:
                            logger.warning(f"Invalid bulk item skipped: {exc}")
                            continue

                    payload = model.model_dump_for_storage()
                    url = payload["url"]

                    # 0. Internal Deduplication (Batch Scope)
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    normalized_published = self._ensure_timezone(
                        payload.get("published_date")
                    )
                    if normalized_published:
                        payload["published_date"] = normalized_published

                    # 1. Existence Check (URL)
                    if (
                        session.query(Article)
                        .filter_by(url=payload["url"])
                        .with_entities(Article.id)
                        .first()
                    ):
                        continue

                    # 2. Preparation
                    norm_title, norm_summary, normalized_text = normalize_article_text(
                        payload.get("title", ""),
                        payload.get("summary", ""),
                    )
                    normalized_basis = normalized_text or payload["url"]
                    content_hash = sha256_hex(normalized_basis)

                    # 3. Content Hash Check
                    if (
                        session.query(Article)
                        .filter_by(content_hash=content_hash)
                        .with_entities(Article.id)
                        .first()
                    ):
                        continue

                    # 4. SimHash & Clustering
                    simhash_value = self._simhash_normalize_unsigned(
                        simhash64(normalized_basis)
                    )
                    simhash_prefix = self._simhash_prefix_value(simhash_value)
                    cluster_id, confidence = self._assign_cluster(
                        session,
                        int(simhash_value) if simhash_value is not None else 0,
                        payload.get("published_date"),
                    )

                    # 5. Model Construction
                    article_metadata = payload.get("article_metadata", {}) or {}
                    article_metadata.setdefault("normalized_title", norm_title)
                    article_metadata.setdefault("normalized_summary", norm_summary)
                    article_metadata.setdefault(
                        "original_url", payload.get("original_url", payload["url"])
                    )

                    article = Article(
                        url=payload["url"],
                        content_hash=content_hash,
                        simhash=self._simhash_to_storage(simhash_value),
                        simhash_prefix=simhash_prefix,
                        title=payload["title"],
                        summary=payload.get("summary"),
                        content=payload.get("content"),
                        source_id=payload["source_id"],
                        source_name=payload["source_name"],
                        published_date=payload.get("published_date"),
                        published_tz_offset_minutes=payload.get(
                            "published_tz_offset_minutes"
                        ),
                        published_tz_name=payload.get("published_tz_name"),
                        authors=payload.get("authors"),
                        category=payload["category"],
                        doi=payload.get("doi"),
                        journal=payload.get("journal"),
                        is_preprint=payload.get("is_preprint", False),
                        language=payload.get("language", "en"),
                        processing_status=PENDING_STATUS,
                        article_metadata=article_metadata,
                        word_count=payload.get("word_count"),
                        reading_time_minutes=payload.get("reading_time_minutes"),
                        cluster_id=cluster_id,
                        duplication_confidence=confidence,
                    )

                    # Apply processing status override if present
                    initial_status = getattr(model, "processing_status_override", None)
                    if initial_status:
                        article.processing_status = initial_status

                    session.add(article)
                    saved_count += 1
                    batch_count += 1

                    if batch_count >= batch_size:
                        session.commit()
                        batch_count = 0

                session.commit()  # Commit leftovers
                logger.info(f"💾 Bulk save completed: {saved_count} articles")
                return saved_count

            except Exception as e:
                session.rollback()
                logger.error(f"Error en bulk save: {e}")
                raise

    @staticmethod
    def _simhash_prefix_value(simhash_value: Optional[int]) -> Optional[int]:
        if simhash_value is None:
            return None
        normalized = simhash_value & SIMHASH_MASK
        return (normalized >> 48) & 0xFFFF

    @staticmethod
    def _ensure_timezone(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _simhash_normalize_unsigned(simhash_value: Optional[int]) -> Optional[int]:
        if simhash_value is None:
            return None
        return simhash_value & SIMHASH_MASK

    @staticmethod
    def _simhash_to_storage(simhash_value: Optional[int]) -> Optional[int]:
        if simhash_value is None:
            return None
        normalized = simhash_value & SIMHASH_MASK
        if normalized >= SIMHASH_SIGN_BIT:
            return normalized - (1 << SIMHASH_BITS)
        return normalized

    @staticmethod
    def _simhash_from_storage(simhash_value: Optional[int]) -> Optional[int]:
        if simhash_value is None:
            return None
        if simhash_value < 0:
            return simhash_value + (1 << SIMHASH_BITS)
        return simhash_value

    def _assign_cluster(  # noqa: C901
        self, session: Session, simhash_value: int, published_date: Optional[datetime]
    ) -> Tuple[str, float]:
        simhash_value = self._simhash_normalize_unsigned(simhash_value) or 0
        if not simhash_value:
            return generate_cluster_id(), 0.0

        prefix = self._simhash_prefix_value(simhash_value)
        if prefix is None:
            return generate_cluster_id(), 0.0

        candidate_prefixes = [prefix]
        if prefix > 0:
            candidate_prefixes.append(prefix - 1)
        if prefix < 0xFFFF:
            candidate_prefixes.append(prefix + 1)

        candidates: List[Article] = []
        remaining = self.simhash_candidate_window
        article_id_attr = cast(QueryableAttribute[Any], Article.id)
        article_simhash_attr = cast(QueryableAttribute[Any], Article.simhash)
        article_cluster_id_attr = cast(QueryableAttribute[Any], Article.cluster_id)
        article_published_date_attr = cast(
            QueryableAttribute[Any], Article.published_date
        )
        article_dup_conf_attr = cast(
            QueryableAttribute[Any], Article.duplication_confidence
        )
        article_collected_date_attr = cast(
            QueryableAttribute[Any], Article.collected_date
        )

        for pref in sorted(
            dict.fromkeys(candidate_prefixes), key=lambda p: abs(p - prefix)
        ):
            query = (
                session.query(Article)
                .options(
                    load_only(
                        article_id_attr,
                        article_simhash_attr,
                        article_cluster_id_attr,
                        article_published_date_attr,
                        article_dup_conf_attr,
                        article_collected_date_attr,
                    )
                )
                .filter(Article.simhash_prefix == pref)
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(remaining)
            )
            pref_candidates = query.all()
            candidates.extend(pref_candidates)
            remaining = self.simhash_candidate_window - len(candidates)
            if remaining <= 0:
                break

        if not candidates:
            candidates = (
                session.query(Article)
                .options(
                    load_only(
                        article_id_attr,
                        article_simhash_attr,
                        article_cluster_id_attr,
                        article_published_date_attr,
                        article_dup_conf_attr,
                        article_collected_date_attr,
                    )
                )
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(self.simhash_candidate_window)
                .all()
            )

        if not candidates:
            return generate_cluster_id(), 0.0

        unique_candidates = {}
        for candidate in candidates:
            if candidate.id not in unique_candidates:
                unique_candidates[candidate.id] = candidate
        candidates = list(unique_candidates.values())

        hits: List[Tuple[Article, int]] = []
        for candidate in candidates:
            c_simhash = getattr(candidate, "simhash", None)
            candidate_simhash = self._simhash_from_storage(
                int(c_simhash) if c_simhash is not None else None
            )
            if candidate_simhash is None:
                continue
            distance = hamming_distance(simhash_value, candidate_simhash)
            if distance <= self.simhash_threshold:
                hits.append((candidate, distance))

        if not hits:
            return generate_cluster_id(), 0.0

        def sort_key(item: Tuple[Article, int]):
            candidate, distance = item
            time_delta = self._time_distance_seconds(
                published_date, getattr(candidate, "published_date", None)
            )
            candidate_id = getattr(candidate, "id", 0)
            return (distance, time_delta, -int(candidate_id))

        hits.sort(key=sort_key)
        best_candidate, best_distance = hits[0]

        target_cluster = best_candidate.cluster_id or generate_cluster_id()
        if best_candidate.cluster_id is None:
            best_candidate.cluster_id = target_cluster
        current_confidence = float(
            getattr(best_candidate, "duplication_confidence", 0.0) or 0.0
        )
        best_candidate_record = cast(Any, best_candidate)
        best_candidate_record.duplication_confidence = max(
            current_confidence, float(duplication_confidence(best_distance))
        )

        other_clusters = {
            cand.cluster_id
            for cand, _ in hits
            if cand.cluster_id and cand.cluster_id != target_cluster
        }

        for other_cluster in other_clusters:
            session.query(Article).filter(Article.cluster_id == other_cluster).update(
                {"cluster_id": target_cluster}, synchronize_session=False
            )

        return str(target_cluster), float(duplication_confidence(best_distance))

    @staticmethod
    def _time_distance_seconds(a: Optional[datetime], b: Optional[datetime]) -> float:
        if not a or not b:
            return float("inf")
        normalized_a = DatabaseManager._ensure_timezone(a)
        normalized_b = DatabaseManager._ensure_timezone(b)
        if normalized_a is None or normalized_b is None:
            return float("inf")
        return abs((normalized_a - normalized_b).total_seconds())

    def _revalidate_cluster(self, session: Session, cluster_id: Optional[str]) -> None:
        if not cluster_id:
            return
        article_id_attr = cast(QueryableAttribute[Any], Article.id)
        article_simhash_attr = cast(QueryableAttribute[Any], Article.simhash)
        article_cluster_id_attr = cast(QueryableAttribute[Any], Article.cluster_id)
        articles = (
            session.query(Article)
            .options(
                load_only(
                    article_id_attr,
                    article_simhash_attr,
                    article_cluster_id_attr,
                )
            )
            .filter(Article.cluster_id == cluster_id)
            .all()
        )
        if len(articles) <= 1:
            return
        anchor = next((a for a in articles if a.simhash is not None), None)
        if anchor is None or anchor.simhash is None:
            return
        anchor_simhash = self._simhash_from_storage(
            int(anchor.simhash) if anchor.simhash is not None else None
        )
        if anchor_simhash is None:
            return
        for article in articles:
            if article.id == anchor.id or article.simhash is None:
                continue
            article_simhash = self._simhash_from_storage(
                int(article.simhash) if article.simhash is not None else None
            )
            if article_simhash is None:
                continue
            distance = hamming_distance(article_simhash, anchor_simhash)
            if distance > self.simhash_threshold * 2:
                new_cluster = generate_cluster_id()
                article_record = cast(Any, article)
                article_record.cluster_id = new_cluster
                article_record.duplication_confidence = 0.0

    def get_articles_by_score(
        self,
        limit: int = 10,
        min_score: float = 0.0,
        exclude_published: bool = False,
    ) -> List[Article]:
        """
        Obtiene los artículos mejor rankeados.

        Es como pedirle al bibliotecario que te traiga los mejores libros
        de la colección según las reseñas y popularidad.
        """
        with self.get_session() as session:
            query = (
                session.query(Article)
                .filter(Article.final_score >= min_score)
                .filter(Article.processing_status == "completed")
            )
            if exclude_published:
                query = query.filter(Article.published_at.is_(None))

            return list(
                query.order_by(desc(Article.final_score), Article.collected_date.desc())
                .limit(limit)
                .all()
            )

    def get_articles_by_category(
        self, category: str, days_back: int = 7
    ) -> List[Article]:
        """
        Obtiene artículos de una categoría específica en los últimos días.

        Como buscar todos los libros de cierto tema que llegaron recientemente.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        with self.get_session() as session:
            results = (
                session.query(Article)
                .filter(Article.category == category)
                .filter(Article.collected_date >= cutoff_date)
                .filter(Article.processing_status == "completed")
                .order_by(desc(Article.final_score), Article.collected_date.desc())
                .all()
            )
            return list(results)

    def get_pending_articles(
        self, limit: Optional[int] = None, status: str = PENDING_STATUS
    ) -> List[Article]:
        """
        Obtiene artículos pendientes de procesamiento (o con otro status).

        Como obtener la lista de libros que llegaron pero aún no han
        sido catalogados apropiadamente.
        """
        with self.get_session() as session:
            query = (
                session.query(Article)
                .filter(Article.processing_status == status)
                .order_by(Article.collected_date)
            )

            if limit:
                query = query.limit(limit)

            pending_articles = query.all()
            session.expunge_all()
            return list(pending_articles)

    def update_validation_status_bulk(self, mappings: List[Dict[str, Any]]) -> bool:
        """
        Actualiza el estado de validación de múltiples artículos en bulk.
        `mappings` debe ser una lista de dicts con la clave "id" y los campos a actualizar:
        [{"id": 1, "processing_status": "validated", "error_message": None}, ...]
        """
        if not mappings:
            return True

        with self.get_session() as session:
            try:
                session.bulk_update_mappings(Article, mappings)
                session.commit()
                return True
            except Exception as e:
                logger.error(f"Error en update_validation_status_bulk: {e}")
                return False

    def update_articles_score_bulk(
        self, score_data_list: List[Tuple[int, ScoringRequestModel | Dict[str, Any]]]
    ) -> bool:
        """
        Actualiza el score de múltiples artículos y registra los cálculos en ScoreLog en bulk.
        """
        if not score_data_list:
            return True

        article_mappings = []
        score_logs = []

        for article_id, score_data in score_data_list:
            if isinstance(score_data, ScoringRequestModel):
                score_model = score_data
            else:
                try:
                    score_model = ScoringRequestModel.model_validate(score_data)
                except ValidationError as exc:
                    logger.error(
                        f"Invalid scoring payload para artículo {article_id}: {exc}"
                    )
                    continue

            payload = score_model.model_dump_for_storage()
            components_model = score_model.components

            article_mappings.append(
                {
                    "id": article_id,
                    "final_score": payload["final_score"],
                    "score_components": payload.get("components", {}),
                    "processing_status": "completed",
                }
            )

            score_logs.append(
                ScoreLog(
                    article_id=article_id,
                    score_version=payload.get("version", "1.0"),
                    source_credibility_score=payload["components"].get(
                        "source_credibility"
                    ),
                    recency_score=payload["components"].get("recency"),
                    content_quality_score=payload["components"].get("content_quality"),
                    engagement_score=components_model.get_engagement_value(),
                    final_score=payload["final_score"],
                    score_explanation=payload.get("explanation", {}),
                    algorithm_weights=payload.get("weights", {}),
                )
            )

        with self.get_session() as session:
            try:
                session.bulk_update_mappings(Article, article_mappings)
                session.add_all(score_logs)
                session.commit()
                return True
            except Exception as e:
                logger.error(f"Error en update_articles_score_bulk: {e}")
                return False

    def update_article_score(
        self, article_id: int, score_data: ScoringRequestModel | Dict[str, Any]
    ) -> bool:
        """
        Actualiza el score de un artículo y registra el cálculo en ScoreLog.

        Es como actualizar la calificación de un libro y mantener un registro
        de por qué recibió esa calificación.
        """
        if isinstance(score_data, ScoringRequestModel):
            score_model = score_data
        else:
            try:
                score_model = ScoringRequestModel.model_validate(score_data)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid scoring payload for article {article_id}: {exc}"
                ) from exc

        payload = score_model.model_dump_for_storage()
        components_model = score_model.components

        with self.get_session() as session:
            try:
                article = session.query(Article).filter_by(id=article_id).first()
                if not article:
                    logger.warning(
                        f"Artículo no encontrado para score update: {article_id}"
                    )
                    return False

                # Actualizar scores en el artículo
                article.final_score = payload["final_score"]
                article.score_components = payload.get("components", {})
                article.processing_status = "completed"

                # Crear registro en ScoreLog
                score_log = ScoreLog(
                    article_id=article_id,
                    score_version=payload.get("version", "1.0"),
                    source_credibility_score=payload["components"].get(
                        "source_credibility"
                    ),
                    recency_score=payload["components"].get("recency"),
                    content_quality_score=payload["components"].get("content_quality"),
                    engagement_score=components_model.get_engagement_value(),
                    final_score=payload["final_score"],
                    score_explanation=payload.get("explanation", {}),
                    algorithm_weights=payload.get("weights", {}),
                )

                session.add(score_log)

                logger.info(
                    f"✅ Score actualizado para artículo {article_id}: {payload['final_score']}"
                )
                return True

            except Exception as e:
                logger.error(f"Error actualizando score: {e}")
                return False

    # =====================================
    # OPERACIONES CON FUENTES
    # =====================================

    def initialize_sources(self, sources_config: Dict[str, Dict]) -> None:
        """
        Inicializa o actualiza la información de fuentes en la base de datos.

        Es como crear fichas para cada uno de nuestros proveedores de libros,
        con toda su información de contacto y estadísticas.
        """
        with self.get_session() as session:
            for source_id, source_config in sources_config.items():
                existing_source = session.query(Source).filter_by(id=source_id).first()

                if existing_source:
                    # Actualizar fuente existente
                    existing_source.name = source_config["name"]
                    existing_source.url = source_config["url"]
                    existing_source.credibility_score = source_config[
                        "credibility_score"
                    ]
                    existing_source.category = source_config["category"]
                    existing_source.update_frequency = source_config.get(
                        "update_frequency"
                    )
                    if source_config.get("etag"):
                        existing_source.feed_etag = source_config["etag"]
                    if source_config.get("last_modified"):
                        existing_source.feed_last_modified = source_config[
                            "last_modified"
                        ]
                else:
                    # Crear nueva fuente
                    new_source = Source(
                        id=source_id,
                        name=source_config["name"],
                        url=source_config["url"],
                        credibility_score=source_config["credibility_score"],
                        category=source_config["category"],
                        update_frequency=source_config.get("update_frequency"),
                        is_active=True,
                        feed_etag=source_config.get("etag"),
                        feed_last_modified=source_config.get("last_modified"),
                    )
                    session.add(new_source)

            logger.info(f"✅ {len(sources_config)} fuentes inicializadas/actualizadas")

    def get_source_feed_metadata(self, source_id: str) -> Dict[str, Optional[str]]:
        """Devuelve los encabezados HTTP cacheados para una fuente."""
        with self.get_session() as session:
            source_etag_attr = cast(QueryableAttribute[Any], Source.feed_etag)
            source_last_modified_attr = cast(
                QueryableAttribute[Any], Source.feed_last_modified
            )
            source = (
                session.query(Source)
                .options(load_only(source_etag_attr, source_last_modified_attr))
                .filter_by(id=source_id)
                .first()
            )
            if not source:
                return {}
            return {
                "etag": source.feed_etag,
                "last_modified": source.feed_last_modified,
            }

    # =====================================
    # OPERACIONES DE ANALÍTICA (DASHBOARD)
    # =====================================

    def get_collection_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """Devuelve estadísticas de recolección diarias de los últimos N días."""
        with self.get_session() as session:
            return collection_stats(session, self.config["type"], days)

    def get_source_performance(self) -> List[Dict[str, Any]]:
        """Devuelve rendimiento promedio por fuente."""
        with self.get_session() as session:
            return source_performance(session)

    def get_category_breakdown(self) -> List[Dict[str, Any]]:
        """Devuelve distribución de artículos por categoría."""
        with self.get_session() as session:
            return category_breakdown(session)

    def get_score_distribution(self, buckets: int = 10) -> Dict[str, int]:
        """Devuelve distribución de scores para histograma."""
        with self.get_session() as session:
            return score_distribution(session, buckets=buckets)

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """Actualiza los encabezados HTTP cacheados después de un fetch."""

        if etag is None and last_modified is None and content_hash is None:
            return

        with self.get_session() as session:
            source = session.query(Source).filter_by(id=source_id).first()
            if not source:
                return
            if etag is not None:
                source.feed_etag = etag
            if last_modified is not None:
                source.feed_last_modified = last_modified
            if content_hash is not None:
                custom_config = dict(source.custom_config or {})
                custom_config["content_hash"] = content_hash
                source.custom_config = custom_config

    def update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        """
        Actualiza las estadísticas de una fuente después de una recolección.

        Como actualizar el expediente de un proveedor con información sobre
        su último envío de libros.
        """
        with self.get_session() as session:
            source = session.query(Source).filter_by(id=source_id).first()
            if source:
                source.last_checked = datetime.now(timezone.utc)
                if stats.get("success", False):
                    source.last_successful_check = datetime.now(timezone.utc)
                    if stats.get("articles_found", 0) > 0:
                        source.last_article_found = datetime.now(timezone.utc)
                        source.total_articles_collected += stats["articles_found"]
                    source.consecutive_failures = 0
                else:
                    source.consecutive_failures += 1
                    source.error_message = stats.get("error_message")

                # Actualizar tasa de éxito
                if source.total_articles_collected > 0:
                    success_rate = 1.0 - (
                        source.consecutive_failures
                        / max(source.total_articles_collected, 1)
                    )
                    source.success_rate = max(0.0, success_rate)

    # =====================================
    # ANÁLISIS Y ESTADÍSTICAS
    # =====================================

    def get_daily_stats(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Obtiene estadísticas diarias del sistema.

        Como obtener un reporte diario de actividad de la biblioteca:
        cuántos libros llegaron, cuáles fueron los más populares, etc.
        """
        with self.get_session() as session:
            return daily_stats(session, date)

    def get_top_sources_performance(self, days_back: int = 30) -> List[Dict[str, Any]]:
        """
        Obtiene el performance de las mejores fuentes en los últimos días.

        Como obtener un ranking de cuáles proveedores han traído
        los mejores libros recientemente.
        """
        with self.get_session() as session:
            return top_sources_performance(session, days_back=days_back)

    # =====================================
    # UTILIDADES Y MANTENIMIENTO
    # =====================================

    def cleanup_old_data(self, days_to_keep: int = 90) -> Dict[str, int]:
        """
        Limpia datos antiguos para mantener la base de datos eficiente.

        Como hacer una limpieza periódica de la biblioteca, archivando
        materiales muy antiguos que ya no son relevantes.
        """
        with self.get_session() as session:
            result = cleanup_old_data(session, days_to_keep)
            logger.info(
                "🧹 Limpieza completada: %s artículos, %s logs eliminados",
                result["deleted_articles"],
                result["deleted_score_logs"],
            )
            return result

    def delete_article(self, article_id: Union[int, str]) -> bool:
        """
        Elimina un artículo específico de la base de datos por ID numérico.
        """
        try:
            num_id = int(article_id)
        except ValueError:
            return False

        with self.get_session() as session:
            try:
                article = session.query(Article).filter(Article.id == num_id).first()
                if article:
                    session.delete(article)
                    return True
            except Exception as e:
                logger.error(f"Error borrando artículo {article_id}: {e}")
        return False

    def clear_all_articles(self) -> int:
        """
        Elimina TODOS los artículos recolectados de la base de datos.

        Esta operación es destructiva e irreversible. Equivale a un "Factory Reset"
        del contenido recolectado.
        """
        with self.get_session() as session:
            try:
                # Eliminar logs de scoring primero para evitar problemas de FK si no hay cascade
                deleted_logs = session.query(ScoreLog).delete()
                # Eliminar artículos
                deleted_articles = session.query(Article).delete()

                # Opcional: Resetear timestamps de fuentes para que vuelvan a buscar todo?
                # Si borramos el contenido, las fuentes deberían poder volver a traerlo si el feed lo tiene.
                # No reseteamos las métricas de fuentes (consecutive_failures etc) para mantener historia de salud.

                logger.info(
                    f"🚨 CACHÉ VACIADA: {deleted_articles} artículos y {deleted_logs} logs eliminados."
                )
                return int(deleted_articles)
            except Exception as e:
                logger.error(f"Error vaciando caché: {e}")
                raise

    def get_health_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado de salud general del sistema de base de datos.

        Como hacer un chequeo médico completo de nuestra biblioteca digital.
        """
        with self.get_session() as session:
            return health_status(session, self.config["type"])


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
