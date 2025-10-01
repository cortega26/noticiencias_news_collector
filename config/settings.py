# config/settings.py
# Configuración central del News Collector System
# ==============================================

import os
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env
load_dotenv()

# Rutas del proyecto
# ==================
# Usamos pathlib porque es más robusto y moderno que os.path
BASE_DIR = Path(__file__).parent.parent  # Directorio raíz del proyecto
DATA_DIR = BASE_DIR / "data"  # Donde guardamos la base de datos
LOGS_DIR = DATA_DIR / "logs"  # Donde guardamos los logs
DLQ_DIR = DATA_DIR / "dlq"  # Dead-letter queue para fallos persistentes

# Crear directorios si no existen
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
DLQ_DIR.mkdir(exist_ok=True)

# Detección del entorno
# =====================
def _detect_environment() -> str:
    """Return the normalized runtime environment name."""

    candidates = [
        os.getenv("ENV"),
        os.getenv("APP_ENV"),
        os.getenv("ENVIRONMENT"),
    ]
    for candidate in candidates:
        if candidate:
            normalized = candidate.strip().lower()
            if normalized:
                return normalized
    return "development"


ENVIRONMENT = _detect_environment()
IS_PRODUCTION = ENVIRONMENT in {"production", "prod"}
IS_STAGING = ENVIRONMENT in {"staging", "stage"}


def _build_database_config() -> Dict[str, Any]:
    """Compose the database configuration based on the environment."""

    if IS_PRODUCTION or IS_STAGING:
        return {
            "type": "postgresql",
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", 5432)),
            "name": os.getenv("DB_NAME", "news_collector"),
            "user": os.getenv("DB_USER", "collector"),
            "password": os.getenv("DB_PASSWORD", ""),
            "sslmode": os.getenv("DB_SSLMODE"),
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", 10)),
            "statement_timeout": int(os.getenv("DB_STATEMENT_TIMEOUT", 30000)),
            "pool_size": int(os.getenv("DB_POOL_SIZE", 10)),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", 5)),
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", 30)),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", 1800)),
        }

    return {
        "type": "sqlite",
        "path": DATA_DIR / "news.db",
    }


# Configuración de Base de Datos
# ==============================
DATABASE_CONFIG = _build_database_config()

# Configuración de Colección
# ==========================
COLLECTION_CONFIG = {
    # Frecuencia de recolección (en horas)
    "collection_interval": int(os.getenv("COLLECTION_INTERVAL", 6)),
    # Timeout para requests HTTP (en segundos)
    "request_timeout": int(os.getenv("REQUEST_TIMEOUT", 30)),
    # Ejecución asíncrona (httpx) opcional para mayor throughput
    "async_enabled": os.getenv("ASYNC_ENABLED", "false").lower() == "true",
    "max_concurrent_requests": int(os.getenv("MAX_CONCURRENT_REQUESTS", 8)),
    # Número máximo de artículos por fuente por colección
    "max_articles_per_source": int(os.getenv("MAX_ARTICLES_PER_SOURCE", 50)),
    # Días hacia atrás para considerar artículos como "recientes"
    "recent_days_threshold": int(os.getenv("RECENT_DAYS_THRESHOLD", 7)),
    # User agent para requests (importante para no ser bloqueado)
    "user_agent": "NoticienciasBot/1.0 (Scientific News Aggregator; +https://noticiencias.com)",
}

# Configuración de Scoring
# ========================
SCORING_CONFIG = {
    # Pesos para diferentes dimensiones del scoring (deben sumar 1.0)
    "weights": {
        "source_credibility": float(os.getenv("WEIGHT_SOURCE", 0.25)),
        "recency": float(os.getenv("WEIGHT_RECENCY", 0.20)),
        "content_quality": float(os.getenv("WEIGHT_CONTENT", 0.25)),
        "engagement_potential": float(os.getenv("WEIGHT_ENGAGEMENT", 0.30)),
    },
    # Número de top noticias a seleccionar diariamente
    "daily_top_count": int(os.getenv("DAILY_TOP_COUNT", 10)),
    # Score mínimo para considerar una noticia
    "minimum_score": float(os.getenv("MINIMUM_SCORE", 0.3)),
    # Modo de scoring: "basic" o "advanced"
    "mode": os.getenv("SCORING_MODE", "advanced"),
    # Configuración de features para el nuevo scorer
    "feature_weights": {
        "source_credibility": float(os.getenv("FEATURE_WEIGHT_SOURCE", 0.30)),
        "freshness": float(os.getenv("FEATURE_WEIGHT_FRESHNESS", 0.25)),
        "content_quality": float(os.getenv("FEATURE_WEIGHT_CONTENT", 0.25)),
        "engagement": float(os.getenv("FEATURE_WEIGHT_ENGAGEMENT", 0.20)),
    },
    "workers": int(os.getenv("SCORING_WORKERS", 4)),
    "freshness": {
        "half_life_hours": float(os.getenv("FRESHNESS_HALF_LIFE_HOURS", 18.0)),
        "max_decay_hours": float(os.getenv("FRESHNESS_MAX_DECAY_HOURS", 168.0)),
    },
    "diversity_penalty": {
        "weight": float(os.getenv("DIVERSITY_PENALTY_WEIGHT", 0.15)),
        "max_penalty": float(os.getenv("DIVERSITY_MAX_PENALTY", 0.3)),
    },
    "content_quality_heuristics": {
        "title_length_divisor": float(os.getenv("SCORING_TITLE_LENGTH_DIVISOR", 120.0)),
        "summary_length_divisor": float(
            os.getenv("SCORING_SUMMARY_LENGTH_DIVISOR", 400.0)
        ),
        "entity_target_count": float(os.getenv("SCORING_ENTITY_TARGET_COUNT", 5.0)),
        "weights": {
            "title": float(os.getenv("SCORING_CONTENT_WEIGHT_TITLE", 0.4)),
            "summary": float(os.getenv("SCORING_CONTENT_WEIGHT_SUMMARY", 0.4)),
            "entity": float(os.getenv("SCORING_CONTENT_WEIGHT_ENTITY", 0.2)),
        },
    },
    "engagement_heuristics": {
        "sentiment_scores": {
            "positive": float(os.getenv("SCORING_SENTIMENT_POSITIVE", 0.7)),
            "negative": float(os.getenv("SCORING_SENTIMENT_NEGATIVE", 0.6)),
            "neutral": float(os.getenv("SCORING_SENTIMENT_NEUTRAL", 0.5)),
        },
        "fallback_sentiment": float(os.getenv("SCORING_SENTIMENT_FALLBACK", 0.5)),
        "word_count_divisor": float(os.getenv("SCORING_WORD_COUNT_DIVISOR", 800.0)),
        "external_weight": float(os.getenv("SCORING_ENGAGEMENT_EXTERNAL_WEIGHT", 0.6)),
        "length_weight": float(os.getenv("SCORING_ENGAGEMENT_LENGTH_WEIGHT", 0.4)),
    },
    "reranker_seed": int(os.getenv("RERANKER_SEED", 1337)),
    "source_cap_percentage": float(os.getenv("SOURCE_CAP_PERCENTAGE", 0.5)),
    "topic_cap_percentage": float(os.getenv("TOPIC_CAP_PERCENTAGE", 0.6)),
}

# Configuración de Logging
# ========================
LOGGING_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "file_path": LOGS_DIR / "collector.log",
    "max_file_size": "10 MB",
    "retention": "30 days",
    "format": "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
}

# Configuración de Procesamiento de Texto
# =======================================
TEXT_PROCESSING_CONFIG = {
    # Idiomas a detectar y procesar
    "supported_languages": ["en", "es", "pt", "fr"],
    # Longitud mínima de contenido para ser considerado válido
    "min_content_length": int(os.getenv("MIN_CONTENT_LENGTH", 100)),
    # Palabras clave que aumentan la relevancia
    "boost_keywords": [
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
    # Palabras que reducen la credibilidad (clickbait indicators)
    "penalty_keywords": [
        "shocking",
        "you won't believe",
        "doctors hate",
        "miracle cure",
        "secret",
        "conspiracy",
        "hoax",
        "fake news",
    ],
}

_DEFAULT_ENRICHMENT_MODEL = os.getenv("ENRICHMENT_MODEL_KEY", "pattern_v1")
_DEFAULT_ENRICHMENT_PROVIDER = os.getenv("ENRICHMENT_PROVIDER", "pattern")

ENRICHMENT_CONFIG = {
    "default_model": _DEFAULT_ENRICHMENT_MODEL,
    "analysis_cache_size": int(os.getenv("ENRICHMENT_ANALYSIS_CACHE", 512)),
    "result_cache_size": int(os.getenv("ENRICHMENT_RESULT_CACHE", 256)),
    "models": {
        "pattern_v1": {
            "version": os.getenv("ENRICHMENT_MODEL_VERSION", "2025.02-pattern-v1"),
            "provider": _DEFAULT_ENRICHMENT_PROVIDER,
            "languages": ["en", "es", "pt", "fr"],
            "default_language": "en",
            "default_topic": "general",
            "entities": {
                "patterns": {
                    "shared": [
                        {"label": "ORG", "pattern": "NASA"},
                        {"label": "ORG", "pattern": "ESA", "alias": "ESA"},
                        {"label": "ORG", "pattern": "IMF"},
                        {"label": "ORG", "pattern": "ONU"},
                    ],
                    "en": [
                        {"label": "EVENT", "pattern": "Artemis II"},
                        {"label": "PRODUCT", "pattern": "Orion"},
                    ],
                    "es": [
                        {
                            "label": "ORG",
                            "pattern": "Ministerio de Salud de Chile",
                        },
                        {
                            "label": "ORG",
                            "pattern": "Universidad Nacional Autónoma de México",
                        },
                    ],
                    "pt": [
                        {"label": "ORG", "pattern": "Universidade de São Paulo"},
                        {"label": "LOC", "pattern": "Amazônia"},
                    ],
                    "fr": [
                        {
                            "label": "ORG",
                            "pattern": "Agence spatiale européenne",
                        },
                        {"label": "PRODUCT", "pattern": "Ariane 6"},
                    ],
                }
            },
            "topics": {
                "space": {
                    "keywords": {
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
                },
                "science": {
                    "keywords": {
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
                },
                "health": {
                    "keywords": {
                        "shared": ["health", "salud", "santé", "sanitario"],
                        "en": ["ministry of health", "hospital"],
                        "es": ["ministerio de salud", "hospital"],
                        "pt": ["saúde", "hospital"],
                        "fr": ["ministère de la santé", "hôpital"],
                    }
                },
                "technology": {
                    "keywords": {
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
                },
                "climate": {
                    "keywords": {
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
                },
                "economy": {
                    "keywords": {
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
                },
            },
            "sentiment": {
                "default": "neutral",
                "tie_breaker": "neutral",
                "lexicon": {
                    "shared_positive": [
                        "confirmed",
                        "progress",
                        "celebrated",
                        "avance",
                        "avances",
                        "innovador",
                        "soluciones",
                        "parceria",
                        "sucesso",
                    ],
                    "shared_negative": [
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
                    "en": {
                        "positive": ["confirmed", "progress", "celebrated"],
                        "negative": ["warned", "recession", "risk", "negative"],
                    },
                    "es": {
                        "positive": ["avance", "celebró", "soluciones"],
                        "negative": ["alerta", "preocupante", "urgente", "urgentes"],
                    },
                    "pt": {
                        "positive": ["celebraram", "parceria", "inovador"],
                        "negative": ["crise", "alerta"],
                    },
                    "fr": {
                        "positive": ["succès", "avancée"],
                        "negative": ["alerte", "inquiétude"],
                    },
                },
            },
        }
    },
}

# Configuración de Rate Limiting
# ==============================
# Esto es crucial para ser un "buen ciudadano" de internet
RATE_LIMITING_CONFIG = {
    # Segundos entre requests a la misma fuente
    "delay_between_requests": float(os.getenv("REQUEST_DELAY", 1.0)),
    # Delay mínimo por dominio (puede ser aumentado por robots.txt)
    "domain_default_delay": float(os.getenv("DOMAIN_DEFAULT_DELAY", 1.0)),
    # Overrides específicos por dominio cuando se requiere más paciencia
    "domain_overrides": {
        "export.arxiv.org": 20.0,
        "arxiv.org": 20.0,
        "www.reddit.com": 30.0,
        "reddit.com": 30.0,
    },
    # Número máximo de reintentos para requests fallidos
    "max_retries": int(os.getenv("MAX_RETRIES", 3)),
    # Tiempo de espera entre reintentos (segundos)
    "retry_delay": int(os.getenv("RETRY_DELAY", 1)),
    # Parámetros de backoff exponencial con jitter
    "backoff_base": float(os.getenv("BACKOFF_BASE", 0.5)),
    "backoff_max": float(os.getenv("BACKOFF_MAX", 10.0)),
    "jitter_max": float(os.getenv("JITTER_MAX", 0.3)),
}

# Cumplimiento robots.txt / ToS
ROBOTS_CONFIG = {
    "respect_robots": os.getenv("RESPECT_ROBOTS", "true").lower() == "true",
    "cache_ttl_seconds": int(os.getenv("ROBOTS_CACHE_TTL", 3600)),
}

# Configuración de deduplicación
DEDUP_CONFIG = {
    "simhash_threshold": int(os.getenv("SIMHASH_THRESHOLD", 10)),
    "simhash_candidate_window": int(os.getenv("SIMHASH_CANDIDATE_WINDOW", 500)),
}


# Validación de configuración
# ===========================
def validate_config():
    """
    Valida que la configuración sea coherente y completa.
    Es como hacer un checklist antes del despegue.
    """
    # Verificar que los pesos del scoring sumen 1.0
    weights_sum = sum(SCORING_CONFIG["weights"].values())
    if abs(weights_sum - 1.0) > 0.01:  # Tolerancia para errores de floating point
        raise ValueError(f"Los pesos de scoring deben sumar 1.0, actual: {weights_sum}")

    feature_weights_sum = sum(SCORING_CONFIG["feature_weights"].values())
    if abs(feature_weights_sum - 1.0) > 0.01:
        raise ValueError(
            f"Los feature_weights del scorer deben sumar 1.0, actual: {feature_weights_sum}"
        )

    # Verificar que los directorios existan
    if not DATA_DIR.exists():
        raise ValueError(f"Directorio de datos no existe: {DATA_DIR}")

    # Verificar configuración de base de datos
    if DATABASE_CONFIG["type"] not in ["sqlite", "postgresql", "mysql"]:
        raise ValueError(
            f"Tipo de base de datos no soportado: {DATABASE_CONFIG['type']}"
        )

    if DATABASE_CONFIG["type"] == "sqlite":
        if "path" not in DATABASE_CONFIG:
            raise ValueError("Config SQLite requiere clave 'path'")

    if DATABASE_CONFIG["type"] == "postgresql":
        required_keys = ["host", "port", "name", "user"]
        missing = [key for key in required_keys if not DATABASE_CONFIG.get(key)]
        if missing:
            raise ValueError(
                "Config Postgres incompleta, faltan claves: " + ", ".join(missing)
            )
        if int(DATABASE_CONFIG.get("pool_size", 0)) <= 0:
            raise ValueError("Postgres pool_size debe ser mayor que cero")
        if int(DATABASE_CONFIG.get("pool_timeout", 0)) <= 0:
            raise ValueError("Postgres pool_timeout debe ser mayor que cero")

    print("✅ Configuración validada correctamente")


# Configuración de desarrollo vs producción
# =========================================
_debug_flag = os.getenv("DEBUG")
if _debug_flag is None:
    DEBUG = not (IS_PRODUCTION or IS_STAGING)
else:
    DEBUG = _debug_flag.lower() == "true"

if DEBUG:
    # En modo desarrollo, más verbose y timeouts más largos
    LOGGING_CONFIG["level"] = "DEBUG"
    COLLECTION_CONFIG["request_timeout"] = 60
    SCORING_CONFIG["daily_top_count"] = 5  # Menos artículos para testing
else:
    # En producción, más conservador
    COLLECTION_CONFIG["max_articles_per_source"] = 20
    RATE_LIMITING_CONFIG["delay_between_requests"] = 2.0
