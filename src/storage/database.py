# src/storage/database.py
# Manejador de base de datos para News Collector System
# ====================================================

"""
Este archivo es el cerebro operativo de nuestro sistema de almacenamiento.
Es como tener un bibliotecario súper eficiente que sabe exactamente dónde
guardar cada pieza de información y cómo recuperarla rápidamente cuando
la necesitemos.

La filosofía aquí es crear una capa de abstracción que nos permita cambiar
de SQLite a PostgreSQL en el futuro sin tocar el resto del código.
"""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import create_engine, desc, func, inspect, text
from sqlalchemy.orm import sessionmaker, Session, load_only
from sqlalchemy.exc import IntegrityError

from pydantic import ValidationError

from ..storage.models import Base, Article, Source, ScoreLog
from config.settings import DATABASE_CONFIG, DEDUP_CONFIG
from ..utils.dedupe import (
    normalize_article_text,
    sha256_hex,
    simhash64,
    hamming_distance,
    duplication_confidence,
    generate_cluster_id,
)
from src.contracts import CollectorArticleModel, ScoringRequestModel

import logging

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
    """

    def __init__(self, database_config: Dict[str, Any] = None):
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
                        "timeout": 20,  # Timeout de 20 segundos para locks
                    },
                    pool_pre_ping=True,  # Verifica conexiones antes de usarlas
                )

            elif self.config["type"] == "postgresql":
                # Para PostgreSQL futuro
                database_url = (
                    f"postgresql://{self.config['user']}:{self.config['password']}"
                    f"@{self.config['host']}:{self.config['port']}/{self.config['name']}"
                )
                self.engine = create_engine(
                    database_url,
                    echo=False,
                    pool_size=5,  # Pool de conexiones para mejor performance
                    max_overflow=10,
                    pool_pre_ping=True,
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

            # Ejecutar migraciones ligeras para mantener el esquema al día
            self._run_schema_migrations()

            logger.info(
                f"✅ Base de datos configurada exitosamente: {self.config['type']}"
            )

        except Exception as e:
            logger.error(f"❌ Error configurando base de datos: {e}")
            raise

    def _run_schema_migrations(self) -> None:
        """Aplica migraciones ligeras necesarias para el esquema actual."""

        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
        except Exception as exc:  # pragma: no cover - solo en errores del driver
            logger.error("No se pudo inspeccionar la base de datos: %s", exc)
            return

        if "sources" not in tables:
            return

        existing_columns = {col["name"] for col in inspector.get_columns("sources")}

        db_type = self.config.get("type", "sqlite")
        timestamp_type = (
            "TIMESTAMP WITH TIME ZONE" if db_type == "postgresql" else "TIMESTAMP"
        )
        boolean_type = "BOOLEAN" if db_type != "sqlite" else "INTEGER"

        migrations: List[Tuple[str, str]] = []

        if "suppressed_until" not in existing_columns:
            migrations.append(
                (
                    f"ALTER TABLE sources ADD COLUMN suppressed_until {timestamp_type}",
                    "suppressed_until",
                )
            )

        if "suppression_reason" not in existing_columns:
            migrations.append(
                (
                    "ALTER TABLE sources ADD COLUMN suppression_reason TEXT",
                    "suppression_reason",
                )
            )

        if "auto_suppressed" not in existing_columns:
            default_clause = "DEFAULT 0" if db_type == "sqlite" else "DEFAULT FALSE"
            migrations.append(
                (
                    f"ALTER TABLE sources ADD COLUMN auto_suppressed {boolean_type} {default_clause}",
                    "auto_suppressed",
                )
            )

        if "dq_consecutive_anomalies" not in existing_columns:
            migrations.append(
                (
                    "ALTER TABLE sources ADD COLUMN dq_consecutive_anomalies INTEGER DEFAULT 0",
                    "dq_consecutive_anomalies",
                )
            )

        if "last_canary_check" not in existing_columns:
            migrations.append(
                (
                    f"ALTER TABLE sources ADD COLUMN last_canary_check {timestamp_type}",
                    "last_canary_check",
                )
            )

        if "last_canary_status" not in existing_columns:
            migrations.append(
                (
                    "ALTER TABLE sources ADD COLUMN last_canary_status TEXT",
                    "last_canary_status",
                )
            )

        if "feed_etag" not in existing_columns:
            migrations.append(
                (
                    "ALTER TABLE sources ADD COLUMN feed_etag TEXT",
                    "feed_etag",
                )
            )

        if "feed_last_modified" not in existing_columns:
            migrations.append(
                (
                    "ALTER TABLE sources ADD COLUMN feed_last_modified TEXT",
                    "feed_last_modified",
                )
            )

        if not migrations:
            return

        with self.engine.begin() as connection:
            for statement, column_name in migrations:
                connection.execute(text(statement))
                logger.info(
                    "🛠️  Columna '%s' agregada a la tabla sources mediante migración automática",
                    column_name,
                )

    @contextmanager
    def get_session(self):
        """
        Context manager para manejar sesiones de base de datos de manera segura.

        Esto es como tener un sistema de préstamo de libros que automáticamente
        registra cuando tomas un libro y cuando lo devuelves, asegurándose
        de que todo esté siempre en orden.

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

    # =====================================
    # OPERACIONES CON ARTÍCULOS
    # =====================================

    def save_article(
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
                existing = session.query(Article).filter_by(url=payload["url"]).first()
                if existing:
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
                    session, simhash_value, payload.get("published_date")
                )

                article_metadata = payload.get("article_metadata", {}) or {}
                article_metadata.setdefault("normalized_title", norm_title)
                article_metadata.setdefault("normalized_summary", norm_summary)
                article_metadata.setdefault(
                    "original_url",
                    payload.get("original_url", payload["url"]),
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
                    processing_status="pending",
                    article_metadata=article_metadata,
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
                logger.warning(f"Intento de guardar artículo duplicado: {e}")
                return None
            except Exception as e:
                logger.error(f"Error guardando artículo: {e}")
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

    def _assign_cluster(
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

        for pref in sorted(
            dict.fromkeys(candidate_prefixes), key=lambda p: abs(p - prefix)
        ):
            query = (
                session.query(Article)
                .options(
                    load_only(
                        Article.id,
                        Article.simhash,
                        Article.cluster_id,
                        Article.published_date,
                        Article.duplication_confidence,
                        Article.collected_date,
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
                        Article.id,
                        Article.simhash,
                        Article.cluster_id,
                        Article.published_date,
                        Article.duplication_confidence,
                        Article.collected_date,
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
            candidate_simhash = self._simhash_from_storage(candidate.simhash)
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
                published_date, candidate.published_date
            )
            return (distance, time_delta, -candidate.id)

        hits.sort(key=sort_key)
        best_candidate, best_distance = hits[0]

        target_cluster = best_candidate.cluster_id or generate_cluster_id()
        if best_candidate.cluster_id is None:
            best_candidate.cluster_id = target_cluster
        best_candidate.duplication_confidence = max(
            best_candidate.duplication_confidence or 0.0,
            duplication_confidence(best_distance),
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

        return target_cluster, duplication_confidence(best_distance)

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
        articles = (
            session.query(Article)
            .options(load_only(Article.id, Article.simhash, Article.cluster_id))
            .filter(Article.cluster_id == cluster_id)
            .all()
        )
        if len(articles) <= 1:
            return
        anchor = next((a for a in articles if a.simhash is not None), None)
        if anchor is None or anchor.simhash is None:
            return
        anchor_simhash = self._simhash_from_storage(anchor.simhash)
        if anchor_simhash is None:
            return
        for article in articles:
            if article.id == anchor.id or article.simhash is None:
                continue
            article_simhash = self._simhash_from_storage(article.simhash)
            if article_simhash is None:
                continue
            distance = hamming_distance(article_simhash, anchor_simhash)
            if distance > self.simhash_threshold * 2:
                new_cluster = generate_cluster_id()
                article.cluster_id = new_cluster
                article.duplication_confidence = 0.0

    def get_articles_by_score(
        self, limit: int = 10, min_score: float = 0.0
    ) -> List[Article]:
        """
        Obtiene los artículos mejor rankeados.

        Es como pedirle al bibliotecario que te traiga los mejores libros
        de la colección según las reseñas y popularidad.
        """
        with self.get_session() as session:
            return (
                session.query(Article)
                .filter(Article.final_score >= min_score)
                .filter(Article.processing_status == "completed")
                .order_by(desc(Article.final_score), Article.collected_date.desc())
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
            return (
                session.query(Article)
                .filter(Article.category == category)
                .filter(Article.collected_date >= cutoff_date)
                .filter(Article.processing_status == "completed")
                .order_by(desc(Article.final_score), Article.collected_date.desc())
                .all()
            )

    def get_pending_articles(self) -> List[Article]:
        """
        Obtiene artículos pendientes de procesamiento.

        Como obtener la lista de libros que llegaron pero aún no han
        sido catalogados apropiadamente.
        """
        with self.get_session() as session:
            pending_articles = (
                session.query(Article)
                .filter(Article.processing_status == "pending")
                .order_by(Article.collected_date)
                .all()
            )
            session.expunge_all()
            return pending_articles

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
            source = session.query(Source).filter_by(id=source_id).first()
            if not source:
                return {"etag": None, "last_modified": None}
            return {
                "etag": source.feed_etag,
                "last_modified": source.feed_last_modified,
            }

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> None:
        """Actualiza los encabezados HTTP cacheados después de un fetch."""

        if etag is None and last_modified is None:
            return

        with self.get_session() as session:
            source = session.query(Source).filter_by(id=source_id).first()
            if not source:
                return
            if etag is not None:
                source.feed_etag = etag
            if last_modified is not None:
                source.feed_last_modified = last_modified

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

    def get_daily_stats(self, date: datetime = None) -> Dict[str, Any]:
        """
        Obtiene estadísticas diarias del sistema.

        Como obtener un reporte diario de actividad de la biblioteca:
        cuántos libros llegaron, cuáles fueron los más populares, etc.
        """
        if not date:
            date = datetime.now(timezone.utc).date()

        start_date = datetime.combine(date, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        end_date = start_date + timedelta(days=1)

        with self.get_session() as session:
            # Artículos recolectados hoy
            articles_collected = (
                session.query(func.count(Article.id))
                .filter(Article.collected_date >= start_date)
                .filter(Article.collected_date < end_date)
                .scalar()
            )

            # Artículos procesados hoy
            articles_processed = (
                session.query(func.count(Article.id))
                .filter(Article.collected_date >= start_date)
                .filter(Article.collected_date < end_date)
                .filter(Article.processing_status == "completed")
                .scalar()
            )

            # Score promedio de artículos de hoy
            avg_score = (
                session.query(func.avg(Article.final_score))
                .filter(Article.collected_date >= start_date)
                .filter(Article.collected_date < end_date)
                .filter(Article.final_score.isnot(None))
                .scalar()
            )

            # Distribución por categorías
            category_distribution = dict(
                session.query(Article.category, func.count(Article.id))
                .filter(Article.collected_date >= start_date)
                .filter(Article.collected_date < end_date)
                .group_by(Article.category)
                .all()
            )

            return {
                "date": date.isoformat(),
                "articles_collected": articles_collected or 0,
                "articles_processed": articles_processed or 0,
                "processing_rate": (articles_processed / max(articles_collected, 1))
                * 100,
                "average_score": round(avg_score or 0.0, 3),
                "category_distribution": category_distribution,
            }

    def get_top_sources_performance(self, days_back: int = 30) -> List[Dict[str, Any]]:
        """
        Obtiene el performance de las mejores fuentes en los últimos días.

        Como obtener un ranking de cuáles proveedores han traído
        los mejores libros recientemente.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        with self.get_session() as session:
            article_agg = (
                session.query(
                    Article.source_id.label("source_id"),
                    func.count(Article.id).label("article_count"),
                    func.avg(Article.final_score).label("avg_score"),
                    func.max(Article.final_score).label("max_score"),
                )
                .filter(Article.processing_status == "completed")
                .filter(Article.collected_date >= cutoff_date)
                .group_by(Article.source_id)
                .subquery()
            )

            results = (
                session.query(
                    Source.id,
                    Source.name,
                    article_agg.c.article_count,
                    article_agg.c.avg_score,
                    article_agg.c.max_score,
                )
                .join(article_agg, article_agg.c.source_id == Source.id)
                .order_by(desc(article_agg.c.avg_score))
                .all()
            )

            return [
                {
                    "source_id": r.id,
                    "source_name": r.name,
                    "article_count": r.article_count,
                    "average_score": round(r.avg_score or 0.0, 3),
                    "max_score": round(r.max_score or 0.0, 3),
                }
                for r in results
            ]

    # =====================================
    # UTILIDADES Y MANTENIMIENTO
    # =====================================

    def cleanup_old_data(self, days_to_keep: int = 90) -> Dict[str, int]:
        """
        Limpia datos antiguos para mantener la base de datos eficiente.

        Como hacer una limpieza periódica de la biblioteca, archivando
        materiales muy antiguos que ya no son relevantes.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        with self.get_session() as session:
            # Eliminar artículos muy antiguos con score bajo
            old_articles = (
                session.query(Article)
                .filter(Article.collected_date < cutoff_date)
                .filter(Article.final_score < 0.3)
                .count()
            )

            deleted_articles = (
                session.query(Article)
                .filter(Article.collected_date < cutoff_date)
                .filter(Article.final_score < 0.3)
                .delete()
            )

            # Eliminar logs de score muy antiguos
            deleted_logs = (
                session.query(ScoreLog)
                .filter(ScoreLog.calculated_at < cutoff_date)
                .delete()
            )

            logger.info(
                f"🧹 Limpieza completada: {deleted_articles} artículos, {deleted_logs} logs eliminados"
            )

            return {
                "deleted_articles": deleted_articles,
                "deleted_score_logs": deleted_logs,
                "cutoff_date": cutoff_date.isoformat(),
            }

    def get_health_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado de salud general del sistema de base de datos.

        Como hacer un chequeo médico completo de nuestra biblioteca digital.
        """
        with self.get_session() as session:
            total_articles = session.query(func.count(Article.id)).scalar()
            pending_articles = (
                session.query(func.count(Article.id))
                .filter(Article.processing_status == "pending")
                .scalar()
            )

            recent_articles = (
                session.query(func.count(Article.id))
                .filter(
                    Article.collected_date
                    >= datetime.now(timezone.utc) - timedelta(days=1)
                )
                .scalar()
            )

            active_sources = (
                session.query(func.count(Source.id))
                .filter(Source.is_active == True)
                .scalar()
            )

            failed_sources = (
                session.query(func.count(Source.id))
                .filter(Source.consecutive_failures > 3)
                .scalar()
            )

            return {
                "total_articles": total_articles,
                "pending_processing": pending_articles,
                "articles_last_24h": recent_articles,
                "active_sources": active_sources,
                "failed_sources": failed_sources,
                "database_type": self.config["type"],
                "status": (
                    "healthy"
                    if failed_sources == 0 and pending_articles < 100
                    else "warning"
                ),
            }


# Instancia global del manejador de base de datos
# ===============================================
# Esta será nuestra conexión principal que usarán todos los demás módulos

_db_manager = None


def get_database_manager() -> DatabaseManager:
    """
    Función factory para obtener la instancia del DatabaseManager.

    Esto implementa el patrón Singleton, asegurándonos de que solo
    tengamos una conexión a la base de datos en todo el sistema.
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


# ¿Por qué esta arquitectura de base de datos?
# ============================================
#
# 1. ABSTRACCIÓN LIMPIA: El DatabaseManager oculta toda la complejidad
#    de SQLAlchemy del resto del sistema.
#
# 2. GESTIÓN SEGURA DE SESIONES: El context manager asegura que nunca
#    tengamos sesiones colgadas o transacciones incompletas.
#
# 3. OPERACIONES OPTIMIZADAS: Cada método está diseñado para las consultas
#    más comunes que necesitará nuestro sistema.
#
# 4. LOGGING COMPREHENSIVO: Cada operación se registra para facilitar
#    debugging y monitoreo.
#
# 5. ESCALABILIDAD: Fácil migración de SQLite a PostgreSQL cuando crezcamos.
#
# 6. INTEGRIDAD DE DATOS: Manejo robusto de errores y validaciones.
#
# Este sistema es como tener un bibliotecario súper competente que nunca
# se equivoca, nunca pierde un libro, y siempre sabe exactamente dónde
# encontrar lo que necesitas.
