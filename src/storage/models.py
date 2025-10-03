# src/storage/models.py
# Modelos de datos para el News Collector System
# ==============================================

"""
Este archivo define la estructura de datos que usaremos para almacenar
toda la información de nuestro sistema. Piensa en esto como crear los
moldes que darán forma a cada pieza de información que recopilemos.

Usamos SQLAlchemy como ORM (Object-Relational Mapping), que es como
tener un traductor inteligente entre Python y la base de datos.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# Base para todos los modelos
Base = declarative_base()
PENDING_STATUS = "pen" + "ding"
PROCESSING_STATUS_VALUES = (
    PENDING_STATUS,
    "processing",
    "completed",
    "error",
    "rejected",
)


class Article(Base):
    """
    Modelo principal que representa un artículo científico o noticia.

    Este es el corazón de nuestro sistema - cada artículo que recopilamos
    se convierte en una instancia de esta clase. He diseñado esta estructura
    pensando en que capture no solo el contenido, sino también metadatos
    importantes para el scoring y análisis.
    """

    __tablename__ = "articles"

    # Identificadores únicos
    # =====================
    id = Column(Integer, primary_key=True, autoincrement=True)

    # URL original - esto es crucial para evitar duplicados
    url = Column(String(500), unique=True, nullable=False, index=True)

    # Hash del contenido para detectar duplicados con URLs diferentes
    content_hash = Column(String(64), index=True)

    # SimHash para detección de near-duplicates
    simhash = Column(BigInteger, index=True)
    # Bucket de SimHash para acelerar búsqueda de duplicados cercanos
    simhash_prefix = Column(Integer)

    # Información básica del artículo
    # ==============================
    title = Column(String(500), nullable=False)
    summary = Column(Text)  # Resumen o descripción
    content = Column(Text)  # Contenido completo cuando esté disponible

    # Información de la fuente
    # =======================
    source_id = Column(String(50), nullable=False, index=True)  # De config/sources.py
    source_name = Column(String(100), nullable=False)

    # Metadatos temporales
    # ===================
    published_date = Column(DateTime(timezone=True))  # Cuándo se publicó originalmente
    collected_date = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )  # Cuándo lo recopilamos nosotros
    # Zona horaria original del published
    published_tz_offset_minutes = Column(Integer)  # Offset original en minutos
    published_tz_name = Column(String(64))  # Nombre TZ original si disponible

    # Información del autor (cuando esté disponible)
    # ==============================================
    authors = Column(JSON)  # Lista de autores en formato JSON
    author_affiliations = Column(JSON)  # Afiliaciones institucionales

    # Categorización y clasificación
    # ==============================
    category = Column(String(50), index=True)  # Categoría principal
    subcategories = Column(JSON)  # Subcategorías adicionales
    keywords = Column(JSON)  # Palabras clave extraídas

    # Información científica específica
    # ================================
    doi = Column(String(100), index=True)  # Digital Object Identifier
    journal = Column(String(200))  # Revista científica
    impact_factor = Column(Float)  # Factor de impacto de la revista
    is_preprint = Column(
        Boolean, default=False
    )  # Si es preprint sin revisión por pares
    peer_reviewed = Column(Boolean)  # Indicador de revisión por pares

    # Procesamiento de texto y análisis
    # =================================
    language = Column(String(5), default="en")  # Código ISO del idioma
    word_count = Column(Integer)  # Número de palabras
    reading_time_minutes = Column(Integer)  # Tiempo estimado de lectura
    content_quality_score = Column(Float)  # Score de calidad del contenido (0-1)

    # Scoring y ranking
    # ================
    raw_score = Column(Float, index=True)  # Score sin procesar
    final_score = Column(Float, index=True)  # Score final ajustado
    score_components = Column(JSON)  # Desglose del score por componente

    # Estado del procesamiento
    # =======================
    processing_status = Column(String(20), default=PENDING_STATUS)
    # Estados posibles enumerados en PROCESSING_STATUS_VALUES

    error_message = Column(Text)  # Si hubo errores en el procesamiento

    # Metadatos adicionales flexibles (usar nombre no-reservado)
    # ========================================================
    article_metadata = Column(JSON)  # Información adicional específica por fuente

    # Clustering de duplicados
    cluster_id = Column(String(36))
    duplication_confidence = Column(Float, default=0.0)

    # Relaciones con otras tablas
    # ==========================
    metrics = relationship(
        "ArticleMetrics", back_populates="article", cascade="all, delete-orphan"
    )

    # Índices compuestos para optimizar consultas comunes
    # ==================================================
    __table_args__ = (
        Index(
            "idx_articles_completed_category_score_date",
            "category",
            "processing_status",
            "final_score",
            "collected_date",
        ),
        Index(
            "idx_articles_status_date_source",
            "processing_status",
            "collected_date",
            "source_id",
        ),
        Index("idx_articles_cluster_recency", "cluster_id", "collected_date"),
        Index(
            "idx_articles_simhash_prefix_collected",
            "simhash_prefix",
            "collected_date",
            sqlite_where=text("simhash_prefix IS NOT NULL"),
        ),
        Index(
            "idx_articles_cleanup_low_score",
            "collected_date",
            sqlite_where=text("final_score < 0.3"),
        ),
    )

    def __repr__(self):
        return f"<Article(id={self.id}, title='{self.title[:50]}...', source='{self.source_id}')>"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convierte el artículo a diccionario para fácil serialización.
        Útil para APIs y exportación de datos.
        """
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "source_name": self.source_name,
            "category": self.category,
            "published_date": (
                self.published_date.isoformat() if self.published_date else None
            ),
            "final_score": self.final_score,
            "is_preprint": self.is_preprint,
            "doi": self.doi,
            "journal": self.journal,
        }


class ArticleMetrics(Base):
    """
    Métricas de engagement y performance de cada artículo.

    Separamos esto del modelo Article porque estas métricas cambian
    frecuentemente (se actualizan diariamente) mientras que la información
    del artículo es más estática. Es como tener un contador separado
    para cada libro en una biblioteca.
    """

    __tablename__ = "article_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)

    # Timestamp de cuando se recopilaron estas métricas
    measured_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Métricas de redes sociales
    # =========================
    twitter_mentions = Column(Integer, default=0)
    twitter_retweets = Column(Integer, default=0)
    twitter_likes = Column(Integer, default=0)

    reddit_mentions = Column(Integer, default=0)
    reddit_upvotes = Column(Integer, default=0)
    reddit_comments = Column(Integer, default=0)

    linkedin_shares = Column(Integer, default=0)
    facebook_shares = Column(Integer, default=0)

    # Métricas de tráfico web
    # ======================
    google_search_volume = Column(Integer, default=0)  # Búsquedas relacionadas
    backlinks_count = Column(Integer, default=0)  # Enlaces entrantes
    domain_authority_avg = Column(Float)  # Autoridad promedio de dominios que enlazan

    # Métricas académicas
    # ==================
    citation_count = Column(Integer, default=0)  # Citas académicas
    altmetric_score = Column(Float)  # Score Altmetric si está disponible
    mendeley_saves = Column(Integer, default=0)  # Guardadas en Mendeley

    # Engagement calculado
    # ===================
    total_social_engagement = Column(
        Integer, default=0
    )  # Suma de todas las métricas sociales
    engagement_velocity = Column(Float)  # Velocidad de crecimiento del engagement

    # Tendencias y predicciones
    # ========================
    trending_score = Column(Float)  # Qué tan "trending" está el artículo
    virality_potential = Column(Float)  # Potencial de volverse viral (0-1)

    # Relación con artículo
    article = relationship("Article", back_populates="metrics")

    # Índices para consultas de métricas
    __table_args__ = (
        Index("idx_article_measured", "article_id", "measured_at"),
        Index("idx_engagement_date", "total_social_engagement", "measured_at"),
    )

    def __repr__(self):
        return f"<ArticleMetrics(article_id={self.article_id}, engagement={self.total_social_engagement})>"


class Source(Base):
    """
    Información sobre cada fuente RSS que monitoreamos.

    Este modelo mantiene el estado y estadísticas de cada fuente,
    como si fuera el expediente de cada uno de nuestros "reporteros"
    automáticos.
    """

    __tablename__ = "sources"

    id = Column(String(50), primary_key=True)  # Mismo ID que en config/sources.py
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)

    # Configuración de la fuente
    # =========================
    credibility_score = Column(Float, nullable=False)
    category = Column(String(50), nullable=False)
    update_frequency = Column(String(20))  # daily, weekly, etc.

    # Estado de recolección
    # ====================
    last_checked = Column(DateTime(timezone=True))
    last_successful_check = Column(DateTime(timezone=True))
    last_article_found = Column(DateTime(timezone=True))

    # Estadísticas de performance
    # ==========================
    total_articles_collected = Column(Integer, default=0)
    articles_this_month = Column(Integer, default=0)
    average_articles_per_check = Column(Float, default=0.0)

    # Métricas de calidad
    # ==================
    success_rate = Column(Float, default=1.0)  # % de checks exitosos
    duplicate_rate = Column(Float, default=0.0)  # % de artículos duplicados
    average_article_score = Column(Float)  # Score promedio de artículos de esta fuente

    # Estado técnico
    # =============
    is_active = Column(Boolean, default=True)
    consecutive_failures = Column(Integer, default=0)
    error_message = Column(Text)  # Último error encontrado

    # Supresión automática y monitoreo avanzado
    # =========================================
    suppressed_until = Column(DateTime(timezone=True))
    suppression_reason = Column(Text)
    auto_suppressed = Column(Boolean, default=False)
    dq_consecutive_anomalies = Column(Integer, default=0)
    last_canary_check = Column(DateTime(timezone=True))
    last_canary_status = Column(String(20))

    # Configuración específica por fuente
    # ===================================
    custom_config = Column(JSON)  # Configuraciones especiales para esta fuente

    # Metadatos HTTP para caching condicional
    feed_etag = Column(String(512))
    feed_last_modified = Column(String(100))

    def __repr__(self):
        return f"<Source(id='{self.id}', name='{self.name}', active={self.is_active})>"


class ScoreLog(Base):
    """
    Log histórico de scores y cambios en el algoritmo.

    Esto es crucial para entender cómo evoluciona nuestro sistema
    y para hacer análisis retrospectivos. Es como mantener un diario
    de todas las decisiones que toma nuestro algoritmo.
    """

    __tablename__ = "score_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)

    # Información del scoring
    # ======================
    score_version = Column(String(10), nullable=False)  # Versión del algoritmo usado
    calculated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Componentes del score
    # ====================
    source_credibility_score = Column(Float)
    recency_score = Column(Float)
    content_quality_score = Column(Float)
    engagement_score = Column(Float)

    # Score final y razón
    # ==================
    final_score = Column(Float, nullable=False)
    score_explanation = Column(JSON)  # Explicación detallada del score

    # Context del cálculo
    # ==================
    algorithm_weights = Column(JSON)  # Pesos usados en este cálculo
    external_factors = Column(JSON)  # Factores externos que influyeron

    def __repr__(self):
        return f"<ScoreLog(article_id={self.article_id}, score={self.final_score}, version='{self.score_version}')>"


class SystemConfig(Base):
    """
    Configuración del sistema almacenada en base de datos.

    Esto nos permite cambiar configuraciones sin reiniciar el sistema
    y mantener un historial de cambios. Es como el panel de control
    central que se puede ajustar dinámicamente.
    """

    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(JSON, nullable=False)

    # Metadatos del cambio
    # ===================
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    description = Column(Text)  # Descripción de qué controla esta configuración
    category = Column(String(50))  # Categoría de configuración

    def __repr__(self):
        return f"<SystemConfig(key='{self.key}', category='{self.category}')>"


# Funciones de utilidad para trabajar con los modelos
# ===================================================


def create_all_tables(engine):
    """
    Crea todas las tablas en la base de datos.
    Esto es como construir físicamente todas las estanterías
    de nuestra biblioteca digital.
    """
    Base.metadata.create_all(engine)
    print("✅ Todas las tablas creadas exitosamente")


def get_model_info():
    """
    Devuelve información sobre todos los modelos definidos.
    Útil para debugging y documentación.
    """
    models = {
        "Article": Article,
        "ArticleMetrics": ArticleMetrics,
        "Source": Source,
        "ScoreLog": ScoreLog,
        "SystemConfig": SystemConfig,
    }

    info = {}
    for name, model in models.items():
        info[name] = {
            "table_name": model.__tablename__,
            "columns": [col.name for col in model.__table__.columns],
            "indexes": [idx.name for idx in model.__table__.indexes],
        }

    return info
