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
    CheckConstraint,
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Base para todos los modelos


class Base(DeclarativeBase):
    pass


PENDING_STATUS = "pen" + "ding"
PROCESSING_STATUS_VALUES = (
    PENDING_STATUS,
    "processing",
    "publishing",
    "validated",
    "completed",
    "error",
    "rejected",
)
_STATUS_CHECK = "processing_status IN ({})".format(
    ", ".join(f"'{v}'" for v in PROCESSING_STATUS_VALUES)
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
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # URL original - esto es crucial para evitar duplicados
    url: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False, index=True
    )

    # Hash del contenido para detectar duplicados con URLs diferentes
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # SimHash para detección de near-duplicates
    simhash: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # Bucket de SimHash para acelerar búsqueda de duplicados cercanos
    simhash_prefix: Mapped[int | None] = mapped_column(Integer)

    # Información básica del artículo
    # ==============================
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)  # Resumen o descripción
    content: Mapped[str | None] = mapped_column(
        Text
    )  # Contenido completo cuando esté disponible

    # Información de la fuente
    # =======================
    source_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # De config/sources.py
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Metadatos temporales
    # ===================
    published_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )  # Cuándo se publicó originalmente
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # Cuándo publicamos en Noticiencias
    published_url: Mapped[str | None] = mapped_column(
        String(500)
    )  # URL pública en Noticiencias si aplica
    collected_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )  # Cuándo lo recopilamos nosotros
    # Zona horaria original del published
    published_tz_offset_minutes: Mapped[int | None] = mapped_column(
        Integer
    )  # Offset original en minutos
    published_tz_name: Mapped[str | None] = mapped_column(
        String(64)
    )  # Nombre TZ original si disponible

    # Información del autor (cuando esté disponible)
    # ==============================================
    authors: Mapped[Any | None] = mapped_column(
        JSON
    )  # Lista de autores en formato JSON
    author_affiliations: Mapped[Any | None] = mapped_column(
        JSON
    )  # Afiliaciones institucionales

    # Categorización y clasificación
    # ==============================
    category: Mapped[str | None] = mapped_column(
        String(50), index=True
    )  # Categoría principal
    subcategories: Mapped[Any | None] = mapped_column(JSON)  # Subcategorías adicionales
    keywords: Mapped[Any | None] = mapped_column(JSON)  # Palabras clave extraídas

    # Información científica específica
    # ================================
    doi: Mapped[str | None] = mapped_column(
        String(100), index=True
    )  # Digital Object Identifier
    journal: Mapped[str | None] = mapped_column(String(200))  # Revista científica
    impact_factor: Mapped[float | None] = mapped_column(
        Float
    )  # Factor de impacto de la revista
    is_preprint: Mapped[bool | None] = mapped_column(
        Boolean, default=False
    )  # Si es preprint sin revisión por pares
    peer_reviewed: Mapped[bool | None] = mapped_column(
        Boolean
    )  # Indicador de revisión por pares

    # Procesamiento de texto y análisis
    # =================================
    language: Mapped[str | None] = mapped_column(
        String(5), default="en"
    )  # Código ISO del idioma
    content_mode: Mapped[str | None] = mapped_column(
        String(20)
    )  # full_text, summary_only, summary_fallback
    word_count: Mapped[int | None] = mapped_column(Integer)  # Número de palabras
    reading_time_minutes: Mapped[int | None] = mapped_column(
        Integer
    )  # Tiempo estimado de lectura
    content_quality_score: Mapped[float | None] = mapped_column(
        Float
    )  # Score de calidad del contenido (0-1)

    # Scoring y ranking
    # ================
    raw_score: Mapped[float | None] = mapped_column(
        Float, index=True
    )  # Score sin procesar
    final_score: Mapped[float | None] = mapped_column(
        Float, index=True
    )  # Score final ajustado
    score_components: Mapped[Any | None] = mapped_column(
        JSON
    )  # Desglose del score por componente

    # Estado del procesamiento
    # =======================
    processing_status: Mapped[str | None] = mapped_column(
        String(20), default=PENDING_STATUS
    )
    # Estados posibles enumerados en PROCESSING_STATUS_VALUES

    error_message: Mapped[str | None] = mapped_column(
        Text
    )  # Si hubo errores en el procesamiento

    # Metadatos adicionales flexibles (usar nombre no-reservado)
    # ========================================================
    article_metadata: Mapped[Any | None] = mapped_column(
        JSON
    )  # Información adicional específica por fuente

    # Clustering de duplicados
    cluster_id: Mapped[str | None] = mapped_column(String(36))
    duplication_confidence: Mapped[float | None] = mapped_column(Float, default=0.0)

    # Identidad Canónica (Fix S2/D1)
    # =============================
    # Esto garantiza que la URL sea estable e independiente del tiempo de procesamiento.
    canonical_slug: Mapped[str | None] = mapped_column(
        String(200), unique=True, index=True
    )

    # Relaciones con otras tablas
    # ==========================
    metrics = relationship(
        "ArticleMetrics", back_populates="article", cascade="all, delete-orphan"
    )

    # Índices compuestos para optimizar consultas comunes
    # ==================================================
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_article_status"),
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
            "uq_articles_content_hash",
            "content_hash",
            unique=True,
            sqlite_where=text("content_hash IS NOT NULL"),
            postgresql_where=text("content_hash IS NOT NULL"),
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
            "source_id": self.source_id,
            "source_name": self.source_name,
            "category": self.category,
            "published_date": (
                self.published_date.isoformat() if self.published_date else None
            ),
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "published_url": self.published_url,
            "final_score": self.final_score,
            "is_preprint": self.is_preprint,
            "doi": self.doi,
            "journal": self.journal,
            "components": self.score_components,
            "content_mode": self.content_mode,
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
    status = Column(String(20), default="ACTIVE")  # ACTIVE, COOLDOWN, DEAD
    next_retry_at = Column(DateTime(timezone=True))
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

    # Blacklist management
    # ====================
    blacklisted = Column(Boolean, default=False)
    blacklisted_at = Column(DateTime(timezone=True))
    blacklist_reason = Column(Text)

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

    __table_args__ = (
        Index("idx_score_logs_article_latest", "article_id", "calculated_at"),
    )

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
