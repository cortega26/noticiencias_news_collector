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
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker, Session, load_only
from sqlalchemy.exc import IntegrityError

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

import logging

# Configurar logging para este módulo
logger = logging.getLogger(__name__)


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
                autocommit=False, autoflush=False, bind=self.engine
            )

            # Crear todas las tablas
            Base.metadata.create_all(self.engine)

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

    def save_article(self, article_data: Dict[str, Any]) -> Optional[Article]:
        """
        Guarda un nuevo artículo en la base de datos.

        Esta función es como tener un bibliotecario que verifica que no
        tengas ya el mismo libro antes de agregarlo a la colección,
        y que lo catalogue apropiadamente.

        Args:
            article_data: Diccionario con toda la información del artículo

        Returns:
            El artículo guardado o None si ya existía
        """
        with self.get_session() as session:
            try:
                # Verificar si ya existe por URL
                existing = (
                    session.query(Article).filter_by(url=article_data["url"]).first()
                )
                if existing:
                    logger.debug(f"Artículo ya existe: {article_data['url']}")
                    return None

                norm_title, norm_summary, normalized_text = normalize_article_text(
                    article_data.get("title", ""),
                    article_data.get("summary", ""),
                )
                normalized_basis = normalized_text or article_data["url"]
                content_hash = sha256_hex(normalized_basis)

                # Verificar duplicados exactos por hash
                existing_by_content = (
                    session.query(Article).filter_by(content_hash=content_hash).first()
                )
                if existing_by_content:
                    logger.debug(
                        f"Contenido duplicado encontrado para: {article_data['title']}"
                    )
                    return None

                simhash_value = simhash64(normalized_basis)
                simhash_prefix = self._simhash_prefix_value(simhash_value)
                cluster_id, confidence = self._assign_cluster(
                    session, simhash_value, article_data.get("published_date")
                )

                article_metadata = article_data.get("article_metadata", {}) or {}
                article_metadata.setdefault("normalized_title", norm_title)
                article_metadata.setdefault("normalized_summary", norm_summary)
                article_metadata.setdefault(
                    "original_url",
                    article_data.get("original_url", article_data["url"]),
                )

                # Crear nuevo artículo
                article = Article(
                    url=article_data["url"],
                    content_hash=content_hash,
                    simhash=simhash_value,
                    simhash_prefix=simhash_prefix,
                    title=article_data["title"],
                    summary=article_data.get("summary"),
                    content=article_data.get("content"),
                    source_id=article_data["source_id"],
                    source_name=article_data["source_name"],
                    published_date=article_data.get("published_date"),
                    published_tz_offset_minutes=article_data.get(
                        "published_tz_offset_minutes"
                    ),
                    published_tz_name=article_data.get("published_tz_name"),
                    authors=article_data.get("authors"),
                    category=article_data["category"],
                    doi=article_data.get("doi"),
                    journal=article_data.get("journal"),
                    is_preprint=article_data.get("is_preprint", False),
                    language=article_data.get("language", "en"),
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
        return ((simhash_value & ((1 << 64) - 1)) >> 48) & 0xFFFF

    def _assign_cluster(
        self, session: Session, simhash_value: int, published_date: Optional[datetime]
    ) -> Tuple[str, float]:
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
            if candidate.simhash is None:
                continue
            distance = hamming_distance(simhash_value, candidate.simhash)
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
        return abs((a - b).total_seconds())

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
        for article in articles:
            if article.id == anchor.id or article.simhash is None:
                continue
            distance = hamming_distance(article.simhash, anchor.simhash)
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
            return (
                session.query(Article)
                .filter(Article.processing_status == "pending")
                .order_by(Article.collected_date)
                .all()
            )

    def update_article_score(self, article_id: int, score_data: Dict[str, Any]) -> bool:
        """
        Actualiza el score de un artículo y registra el cálculo en ScoreLog.

        Es como actualizar la calificación de un libro y mantener un registro
        de por qué recibió esa calificación.
        """
        with self.get_session() as session:
            try:
                article = session.query(Article).filter_by(id=article_id).first()
                if not article:
                    logger.warning(
                        f"Artículo no encontrado para score update: {article_id}"
                    )
                    return False

                # Actualizar scores en el artículo
                article.final_score = score_data["final_score"]
                article.score_components = score_data.get("components", {})
                article.processing_status = "completed"

                # Crear registro en ScoreLog
                score_log = ScoreLog(
                    article_id=article_id,
                    score_version=score_data.get("version", "1.0"),
                    source_credibility_score=score_data["components"].get(
                        "source_credibility"
                    ),
                    recency_score=score_data["components"].get("recency"),
                    content_quality_score=score_data["components"].get(
                        "content_quality"
                    ),
                    engagement_score=score_data["components"].get("engagement"),
                    final_score=score_data["final_score"],
                    score_explanation=score_data.get("explanation", {}),
                    algorithm_weights=score_data.get("weights", {}),
                )

                session.add(score_log)

                logger.info(
                    f"✅ Score actualizado para artículo {article_id}: {score_data['final_score']}"
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
                    )
                    session.add(new_source)

            logger.info(f"✅ {len(sources_config)} fuentes inicializadas/actualizadas")

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
