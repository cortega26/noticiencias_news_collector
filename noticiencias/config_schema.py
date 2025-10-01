"""Declarative configuration schema for Noticiencias."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    PrivateAttr,
    field_validator,
    model_validator,
)


class SchemaError(ValueError):
    """Raised when the configuration schema definition is invalid."""


class StrictModel(BaseModel):
    """Base model enforcing strict validation rules."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class AppSettings(StrictModel):
    """Top-level runtime metadata."""

    environment: str = Field(
        default="development",
        description="Normalized deployment environment name.",
        examples=["production"],
    )
    debug: bool = Field(
        default=False,
        description="When true, enables verbose logging and relaxed guards.",
    )
    timezone: str = Field(
        default="UTC",
        description="Default timezone for user-facing timestamps.",
        examples=["America/Santiago"],
    )

    @field_validator("environment")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "production", "staging", "test"}:
            raise ValueError(
                "environment must be one of: development, staging, production, test"
            )
        return normalized


class PathsConfig(StrictModel):
    """Filesystem layout settings."""

    data_dir: Path = Field(
        default=Path("data"),
        description="Root directory for persistent runtime artefacts.",
        examples=["/var/lib/noticiencias"],
    )
    logs_dir: Path = Field(
        default=Path("logs"),
        description="Directory where operational logs are written.",
        examples=["/var/log/noticiencias"],
    )
    dlq_dir: Path = Field(
        default=Path("dlq"),
        description="Storage directory for dead-letter queue payloads.",
    )

    @model_validator(mode="after")
    def _ensure_child_paths(self) -> "PathsConfig":
        base = self.data_dir if self.data_dir.is_absolute() else self.data_dir.resolve()
        object.__setattr__(self, "data_dir", base)
        if not self.logs_dir.is_absolute():
            object.__setattr__(self, "logs_dir", (base / self.logs_dir).resolve())
        if not self.dlq_dir.is_absolute():
            object.__setattr__(self, "dlq_dir", (base / self.dlq_dir).resolve())
        return self


class DatabaseConfig(StrictModel):
    """Database connectivity parameters."""

    driver: str = Field(
        default="sqlite",
        description="Database backend driver to use.",
        examples=["postgresql"],
    )
    path: Optional[Path] = Field(
        default=Path("data/news.db"),
        description="Filesystem path for SQLite database files.",
    )
    host: Optional[str] = Field(
        default=None,
        description="Hostname for the SQL server when using a network backend.",
        examples=["db.internal"],
    )
    port: Optional[int] = Field(
        default=None,
        description="TCP port for the SQL server backend.",
        examples=[5432],
    )
    name: str = Field(
        default="noticiencias", description="Database name or schema."  # noqa: E501
    )
    user: Optional[str] = Field(
        default=None,
        description="Database username for authenticated connections.",
    )
    password: Optional[str] = Field(
        default=None,
        description="Database password; treated as secret.",
    )
    sslmode: Optional[str] = Field(
        default=None,
        description="libpq-compatible SSL mode string for PostgreSQL.",
    )
    connect_timeout: PositiveInt = Field(
        default=10, description="Seconds to wait when establishing a connection."
    )
    statement_timeout: PositiveInt = Field(
        default=30_000,
        description="Maximum execution time for SQL statements (ms).",
    )
    pool_size: PositiveInt = Field(
        default=10, description="Number of persistent connections per worker."
    )
    max_overflow: PositiveInt = Field(
        default=5,
        description="How many extra connections can be opened temporarily.",
    )
    pool_timeout: PositiveInt = Field(
        default=30,
        description="Seconds to wait when the pool is exhausted before failing.",
    )
    pool_recycle: PositiveInt = Field(
        default=1_800,
        description="Seconds after which pooled connections are recycled.",
    )

    @model_validator(mode="after")
    def _validate_backend(self) -> "DatabaseConfig":
        driver = self.driver.lower()
        if driver not in {"sqlite", "postgresql"}:
            raise ValueError("driver must be either 'sqlite' or 'postgresql'")
        if driver == "sqlite":
            if not self.path:
                raise ValueError("SQLite configuration requires a file path")
        else:
            missing: list[str] = []
            for field_name in ("host", "port", "user"):
                if getattr(self, field_name) in (None, ""):
                    missing.append(field_name)
            if missing:
                raise ValueError(
                    "PostgreSQL configuration requires fields: " + ", ".join(missing)
                )
            if self.port is not None and self.port <= 0:
                raise ValueError("Database port must be a positive integer")
        return self


class CollectionConfig(StrictModel):
    """News collection behaviour parameters."""

    collection_interval_hours: PositiveInt = Field(
        default=6,
        description="Interval between collector runs in hours.",
    )
    request_timeout_seconds: PositiveInt = Field(
        default=30,
        description="HTTP request timeout used by collectors.",
    )
    async_enabled: bool = Field(
        default=False, description="Enable asyncio-based fetchers when available."
    )
    max_concurrent_requests: PositiveInt = Field(
        default=8,
        description="Concurrency limit for async collectors.",
    )
    max_articles_per_source: PositiveInt = Field(
        default=50,
        description="Cap on articles per source per run.",
    )
    recent_days_threshold: PositiveInt = Field(
        default=7,
        description="Number of trailing days considered 'recent'.",
    )
    user_agent: str = Field(
        default="NoticienciasBot/1.0 (+https://noticiencias.com)",
        description="HTTP User-Agent header sent to providers.",
    )


class RateLimitingConfig(StrictModel):
    """Request throttling configuration."""

    delay_between_requests_seconds: PositiveFloat = Field(
        default=1.0,
        description="Base delay enforced between requests to the same source.",
    )
    domain_default_delay_seconds: PositiveFloat = Field(
        default=1.0,
        description="Fallback delay applied when a domain has no override.",
    )
    domain_overrides: Dict[str, PositiveFloat] = Field(
        default_factory=lambda: {
            "export.arxiv.org": 20.0,
            "arxiv.org": 20.0,
            "www.reddit.com": 30.0,
            "reddit.com": 30.0,
        },
        description="Per-domain throttle overrides in seconds.",
    )
    max_retries: PositiveInt = Field(
        default=3, description="Maximum number of retry attempts per request."
    )
    retry_delay_seconds: PositiveFloat = Field(
        default=1.0,
        description="Initial delay between retries, subject to backoff.",
    )
    backoff_base: PositiveFloat = Field(
        default=0.5, description="Base factor for exponential backoff."  # noqa: E501
    )
    backoff_max: PositiveFloat = Field(
        default=10.0,
        description="Maximum jitter-free delay enforced by backoff.",
    )
    jitter_max: PositiveFloat = Field(
        default=0.3, description="Maximum random jitter added to delays."
    )


class RobotsConfig(StrictModel):
    """Robots.txt compliance toggles."""

    respect_robots: bool = Field(
        default=True, description="Honor robots.txt directives when collecting."
    )
    cache_ttl_seconds: PositiveInt = Field(
        default=3_600,
        description="Seconds to cache robots.txt fetch results.",
    )


class DedupConfig(StrictModel):
    """Document deduplication behaviour."""

    simhash_threshold: PositiveInt = Field(
        default=10, description="Maximum allowed SimHash distance for duplicates."
    )
    simhash_candidate_window: PositiveInt = Field(
        default=500, description="Window size for near-duplicate candidate search."
    )


class WeightsConfig(StrictModel):
    """Helper model storing scoring weights."""

    source_credibility: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Weight applied to source trustworthiness scoring feature.",
    )
    recency: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Weight for publication recency component.",
    )
    content_quality: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Weight for content quality heuristics.",
    )
    engagement_potential: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Weight for predicted audience engagement.",
    )

    @model_validator(mode="after")
    def _check_sum(self) -> "WeightsConfig":
        total = (
            self.source_credibility
            + self.recency
            + self.content_quality
            + self.engagement_potential
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError("Weights must sum to approximately 1.0")
        return self


class FeatureWeightsConfig(StrictModel):
    """Detailed feature weights for advanced scorer."""

    source_credibility: float = Field(default=0.30, ge=0.0, le=1.0)
    freshness: float = Field(default=0.25, ge=0.0, le=1.0)
    content_quality: float = Field(default=0.25, ge=0.0, le=1.0)
    engagement: float = Field(default=0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_sum(self) -> "FeatureWeightsConfig":
        total = (
            self.source_credibility + self.freshness + self.content_quality + self.engagement
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError("Feature weights must sum to approximately 1.0")
        return self


class FreshnessConfig(StrictModel):
    """Freshness decay parameters."""

    half_life_hours: PositiveFloat = Field(default=18.0)
    max_decay_hours: PositiveFloat = Field(default=168.0)


class DiversityPenaltyConfig(StrictModel):
    """Penalty parameters for diversity adjustments."""

    weight: float = Field(default=0.15, ge=0.0, le=1.0)
    max_penalty: float = Field(default=0.30, ge=0.0, le=1.0)


class ContentQualityWeights(StrictModel):
    """Nested weights for content quality heuristics."""

    title: float = Field(default=0.4, ge=0.0, le=1.0)
    summary: float = Field(default=0.4, ge=0.0, le=1.0)
    entity: float = Field(default=0.2, ge=0.0, le=1.0)


class ContentQualityHeuristics(StrictModel):
    """Heuristics for content quality scoring."""

    title_length_divisor: PositiveFloat = Field(default=120.0)
    summary_length_divisor: PositiveFloat = Field(default=400.0)
    entity_target_count: PositiveFloat = Field(default=5.0)
    weights: ContentQualityWeights = Field(default_factory=ContentQualityWeights)


class SentimentScores(StrictModel):
    """Sentiment scoring weights for engagement heuristics."""

    positive: float = Field(default=0.7, ge=0.0, le=1.0)
    negative: float = Field(default=0.6, ge=0.0, le=1.0)
    neutral: float = Field(default=0.5, ge=0.0, le=1.0)


class EngagementHeuristics(StrictModel):
    """Heuristics for engagement potential scoring."""

    sentiment_scores: SentimentScores = Field(default_factory=SentimentScores)
    fallback_sentiment: float = Field(default=0.5, ge=0.0, le=1.0)
    word_count_divisor: PositiveFloat = Field(default=800.0)
    external_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    length_weight: float = Field(default=0.4, ge=0.0, le=1.0)


class ScoringConfig(StrictModel):
    """Scoring engine parameters."""

    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    feature_weights: FeatureWeightsConfig = Field(default_factory=FeatureWeightsConfig)
    daily_top_count: PositiveInt = Field(
        default=10, description="Number of articles promoted per day."
    )
    minimum_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum score required for surfacing an article.",
    )
    mode: str = Field(
        default="advanced",
        description="Active scoring pipeline variant (basic|advanced).",
        examples=["basic"],
    )
    workers: PositiveInt = Field(default=4)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    diversity_penalty: DiversityPenaltyConfig = Field(
        default_factory=DiversityPenaltyConfig
    )
    content_quality_heuristics: ContentQualityHeuristics = Field(
        default_factory=ContentQualityHeuristics
    )
    engagement_heuristics: EngagementHeuristics = Field(
        default_factory=EngagementHeuristics
    )
    reranker_seed: PositiveInt = Field(default=1_337)
    source_cap_percentage: float = Field(default=0.5, ge=0.0, le=1.0)
    topic_cap_percentage: float = Field(default=0.6, ge=0.0, le=1.0)


class TextProcessingConfig(StrictModel):
    """Text normalization options."""

    supported_languages: List[str] = Field(
        default_factory=lambda: ["en", "es", "pt", "fr"],
        description="Languages supported by NLP routines.",
    )
    min_content_length: PositiveInt = Field(
        default=100,
        description="Minimum number of characters required for an article.",
    )
    boost_keywords: List[str] = Field(
        default_factory=lambda: [
            "breakthrough",
            "discovery",
            "research",
            "study",
            "clinical trial",
            "peer-reviewed",
            "published",
            "journal",
            "university",
            "scientists",
            "artificial intelligence",
            "machine learning",
            "climate change",
            "medical",
            "technology",
            "innovation",
            "Nobel",
            "FDA approved",
        ],
        description="Keywords boosting article relevance.",
    )
    penalty_keywords: List[str] = Field(
        default_factory=lambda: [
            "shocking",
            "you won't believe",
            "doctors hate",
            "miracle cure",
            "secret",
            "conspiracy",
            "hoax",
            "fake news",
        ],
        description="Keywords penalizing credibility (clickbait).",
    )


class SentimentLanguageLexicon(StrictModel):
    """Language specific sentiment keywords."""

    positive: List[str] = Field(default_factory=list)
    negative: List[str] = Field(default_factory=list)


class SentimentLexicon(StrictModel):
    """Lexicon entries for sentiment scoring."""

    shared_positive: List[str] = Field(default_factory=list)
    shared_negative: List[str] = Field(default_factory=list)
    languages: Dict[str, SentimentLanguageLexicon] = Field(default_factory=dict)


class SentimentConfig(StrictModel):
    """Sentiment detection configuration."""

    default: str = Field(default="neutral")
    tie_breaker: str = Field(default="neutral")
    lexicon: SentimentLexicon = Field(default_factory=SentimentLexicon)


class TopicConfig(StrictModel):
    """Topic classification keywords."""

    keywords: Dict[str, List[str]] = Field(default_factory=dict)


class EntityPattern(StrictModel):
    """Entity pattern definition."""

    label: str = Field(default="MISC")
    pattern: str = Field(..., min_length=1)
    alias: Optional[str] = Field(default=None)
    case_sensitive: bool = Field(default=False)


class EntityPatterns(StrictModel):
    """Entity pattern collections."""

    entries: Dict[str, List[EntityPattern]] = Field(default_factory=dict)


class ModelConfig(StrictModel):
    """Per-model enrichment configuration."""

    version: str = Field(default="2025.02-pattern-v1")
    provider: str = Field(default="pattern")
    languages: List[str] = Field(default_factory=lambda: ["en", "es", "pt", "fr"])
    default_language: str = Field(default="en")
    default_topic: str = Field(default="general")
    entities: EntityPatterns = Field(default_factory=EntityPatterns)
    topics: Dict[str, TopicConfig] = Field(default_factory=dict)
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig)


class EnrichmentConfig(StrictModel):
    """Configuration for the enrichment pipeline."""

    default_model: str = Field(default="pattern_v1")
    analysis_cache_size: PositiveInt = Field(default=512)
    result_cache_size: PositiveInt = Field(default=256)
    models: Dict[str, ModelConfig] = Field(default_factory=dict)


class NewsConfig(StrictModel):
    """Presentation-layer settings."""

    max_items: PositiveInt = Field(
        default=50,
        description="Maximum number of articles served per request.",
    )
    default_language: str = Field(
        default="es",
        description="Default language when none is specified by the user.",
        examples=["en"],
    )


class LoggingConfig(StrictModel):
    """Logging subsystem configuration."""

    level: str = Field(
        default="INFO",
        description="Minimum log level captured by the collector logger.",
        examples=["DEBUG"],
    )
    file_path: Path = Field(
        default=Path("data/logs/collector.log"),
        description="Absolute path of the rotating log file.",
    )
    max_file_size_mb: PositiveInt = Field(
        default=10,
        description="Maximum size per log file before rotation (MiB).",
    )
    retention_days: PositiveInt = Field(
        default=30,
        description="Number of days to keep rotated log files.",
    )
    format: str = Field(
        default="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
        description="Log formatting template compatible with structlog/loguru.",
    )

    @model_validator(mode="after")
    def _resolve_path(self) -> "LoggingConfig":
        if not self.file_path.is_absolute():
            self.file_path = self.file_path.resolve()
        return self


class Config(StrictModel):
    """Complete Noticiencias configuration model."""

    app: AppSettings = Field(default_factory=AppSettings)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    collection: CollectionConfig = Field(default_factory=CollectionConfig)
    rate_limiting: RateLimitingConfig = Field(default_factory=RateLimitingConfig)
    robots: RobotsConfig = Field(default_factory=RobotsConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    text_processing: TextProcessingConfig = Field(default_factory=TextProcessingConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    _metadata: object = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _ensure_enrichment_models(self) -> "Config":
        if not self.enrichment.models:
            self.enrichment.models = {
                "pattern_v1": ModelConfig(
                    version="2025.02-pattern-v1",
                    provider="pattern",
                    entities=EntityPatterns(
                        entries={
                            "shared": [
                                EntityPattern(label="ORG", pattern="NASA"),
                                EntityPattern(label="ORG", pattern="Google"),
                                EntityPattern(label="LOC", pattern="Mars"),
                                EntityPattern(label="ORG", pattern="ESA"),
                                EntityPattern(label="ORG", pattern="IMF"),
                                EntityPattern(label="ORG", pattern="ONU"),
                            ],
                            "en": [
                                EntityPattern(label="EVENT", pattern="Artemis II"),
                                EntityPattern(label="PRODUCT", pattern="Orion"),
                                EntityPattern(label="ORG", pattern="Wall Street"),
                            ],
                            "es": [
                                EntityPattern(
                                    label="ORG",
                                    pattern="Ministerio de Salud de Chile",
                                ),
                                EntityPattern(
                                    label="ORG",
                                    pattern="Universidad Nacional Autónoma de México",
                                ),
                                EntityPattern(label="ORG", pattern="Telefónica"),
                                EntityPattern(
                                    label="TECH",
                                    pattern="IA",
                                    alias="IA",
                                    case_sensitive=True,
                                ),
                            ],
                            "pt": [
                                EntityPattern(
                                    label="ORG", pattern="Universidade de São Paulo"
                                ),
                                EntityPattern(label="LOC", pattern="Amazônia"),
                            ],
                            "fr": [
                                EntityPattern(
                                    label="ORG", pattern="Agence spatiale européenne"
                                ),
                                EntityPattern(label="PRODUCT", pattern="Ariane 6"),
                            ],
                        }
                    ),
                    topics={
                        "space": TopicConfig(
                            keywords={
                                "shared": [
                                    "space",
                                    "espacio",
                                    "espaço",
                                    "espace",
                                    "lunar",
                                    "orbit",
                                    "orbital",
                                    "rocket",
                                    "cohete",
                                    "foguete",
                                    "fusée",
                                ],
                                "en": ["nasa", "artemis", "orion"],
                                "es": ["nasa", "lunar"],
                                "pt": ["nasa", "orbital"],
                                "fr": ["esa", "ariane", "européenne"],
                            }
                        ),
                        "science": TopicConfig(
                            keywords={
                                "shared": [
                                    "science",
                                    "ciencia",
                                    "ciência",
                                    "scientifique",
                                    "recherche",
                                    "research",
                                    "investigación",
                                    "pesquisa",
                                    "laboratorio",
                                    "laboratory",
                                    "laboratoire",
                                ],
                                "en": ["scientists", "researchers"],
                                "es": [
                                    "investigadores",
                                    "científicos",
                                    "cientifico",
                                    "científica",
                                    "cientificos",
                                    "cientificas",
                                    "equipo científico",
                                ],
                                "pt": ["pesquisadores", "cientistas", "cientista"],
                                "fr": ["chercheurs", "scientifiques"],
                            }
                        ),
                        "health": TopicConfig(
                            keywords={
                                "shared": ["health", "salud", "santé", "sanitario"],
                                "en": ["ministry of health", "hospital"],
                                "es": ["ministerio de salud", "hospital"],
                                "pt": ["saúde", "hospital"],
                                "fr": ["ministère de la santé", "hôpital"],
                            }
                        ),
                        "technology": TopicConfig(
                            keywords={
                                "shared": [
                                    "technology",
                                    "tecnología",
                                    "tecnologia",
                                    "technologie",
                                    "ai",
                                    "ia",
                                    "inteligencia artificial",
                                    "inteligência artificial",
                                ],
                                "en": ["platform", "software"],
                                "es": ["plataforma", "software"],
                                "pt": ["plataforma", "software"],
                                "fr": ["plateforme", "logiciel"],
                            }
                        ),
                        "climate": TopicConfig(
                            keywords={
                                "shared": [
                                    "climate",
                                    "clima",
                                    "climático",
                                    "climática",
                                    "climatique",
                                    "emissions",
                                    "emisiones",
                                    "emissões",
                                    "émissions",
                                    "carbon",
                                    "carbono",
                                    "carbone",
                                ],
                                "en": ["climate", "carbon"],
                                "es": ["emisiones", "climática"],
                                "pt": ["climática", "amazônia"],
                                "fr": ["climatique", "carbone"],
                            }
                        ),
                        "economy": TopicConfig(
                            keywords={
                                "shared": [
                                    "economy",
                                    "economía",
                                    "economia",
                                    "économie",
                                    "market",
                                    "mercado",
                                    "marché",
                                    "inflation",
                                    "recession",
                                    "recesión",
                                    "recessão",
                                ],
                                "en": ["inflation", "recession"],
                                "es": ["inflación", "recesión"],
                                "pt": ["inflação", "recessão"],
                                "fr": ["inflation", "récession"],
                            }
                        ),
                    },
                    sentiment=SentimentConfig(
                        default="neutral",
                        tie_breaker="neutral",
                        lexicon=SentimentLexicon(
                            shared_positive=[
                                "confirmed",
                                "progress",
                                "celebrated",
                                "avance",
                                "avances",
                                "innovador",
                                "innovadora",
                                "soluciones",
                                "parceria",
                                "sucesso",
                            ],
                            shared_negative=[
                                "warned",
                                "risk",
                                "crisis",
                                "preocupante",
                                "urgente",
                                "urgentes",
                                "inflation",
                                "recession",
                                "recesión",
                                "recessão",
                            ],
                            languages={
                                "en": SentimentLanguageLexicon(
                                    positive=["confirmed", "progress", "celebrated"],
                                    negative=["warned", "recession", "risk", "negative"],
                                ),
                                "es": SentimentLanguageLexicon(
                                    positive=[
                                        "avance",
                                        "celebró",
                                        "soluciones",
                                        "positivo",
                                        "positiva",
                                    ],
                                    negative=["alerta", "preocupante", "urgente", "urgentes"],
                                ),
                                "pt": SentimentLanguageLexicon(
                                    positive=["celebraram", "parceria", "inovador"],
                                    negative=["crise", "alerta"],
                                ),
                                "fr": SentimentLanguageLexicon(
                                    positive=["succès", "avancée"],
                                    negative=["alerte", "inquiétude"],
                                ),
                            },
                        ),
                    ),
                )
            }
            self.enrichment.default_model = "pattern_v1"
        return self


DEFAULT_CONFIG = Config()


def iter_field_docs(
    model: BaseModel | type[BaseModel],
    prefix: str = "",
    *,
    include_defaults: bool = True,
) -> Iterable[dict[str, object]]:
    """Yield flattened schema documentation entries."""

    instance = DEFAULT_CONFIG if isinstance(model, type) else model
    target_model = type(instance) if not isinstance(model, type) else model

    for name, field in target_model.model_fields.items():
        value = getattr(instance, name, field.default)
        key = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
        is_nested = isinstance(value, BaseModel)
        entry: dict[str, object] = {
            "name": key,
            "type": getattr(field.annotation, "__name__", str(field.annotation)),
            "description": field.description or "",
            "default": None if (is_nested or not include_defaults) else value,
            "examples": field.examples or [],
            "constraints": _describe_constraints(field),
            "is_nested": is_nested,
        }
        yield entry
        if is_nested:
            yield from iter_field_docs(value, key)


def _describe_constraints(field: Any) -> str:
    """Return a human readable description of field constraints."""

    parts: list[str] = []
    for attr in ("ge", "gt", "le", "lt", "max_length", "min_length"):
        bound = getattr(field, attr, None)
        if bound is not None:
            comparator = {
                "ge": ">=",
                "gt": ">",
                "le": "<=",
                "lt": "<",
                "max_length": "len<=",
                "min_length": "len>=",
            }[attr]
            parts.append(f"{comparator} {bound}")
    return ", ".join(parts)


__all__ = [
    "Config",
    "DEFAULT_CONFIG",
    "SchemaError",
    "iter_field_docs",
]
