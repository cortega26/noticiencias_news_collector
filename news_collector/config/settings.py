"""Project configuration facade backed by noticiencias.config_manager."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from noticiencias.config_manager import Config, ConfigError, load_config

_CONFIG_STATE: Any | None = None


class _RuntimeConfigProxy:
    """Stable object reference that always exposes the latest loaded config."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_config(), name)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return repr(get_config())


CONFIG = _RuntimeConfigProxy()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DLQ_DIR = BASE_DIR / "dlq"

DATABASE_CONFIG: Dict[str, Any] = {}
COLLECTION_CONFIG: Dict[str, Any] = {}
RATE_LIMITING_CONFIG: Dict[str, Any] = {}
ROBOTS_CONFIG: Dict[str, Any] = {}
DEDUP_CONFIG: Dict[str, Any] = {}
SCORING_CONFIG: Dict[str, Any] = {}
TEXT_PROCESSING_CONFIG: Dict[str, Any] = {}
ENRICHMENT_CONFIG: Dict[str, Any] = {}
NEWS_CONFIG: Dict[str, Any] = {}
GEMINI_CONFIG: Dict[str, Any] = {}
LOGGING_CONFIG: Dict[str, Any] = {}

ENVIRONMENT = "development"
DEBUG = False
IS_PRODUCTION = False
IS_STAGING = False


def _replace_mapping(target: Dict[str, Any], new_values: Dict[str, Any]) -> None:
    target.clear()
    target.update(new_values)


def _normalize_enrichment(config: Config) -> Dict[str, Any]:
    data = config.enrichment.model_dump(mode="python")
    models: Dict[str, Any] = {}
    for key, model in data.get("models", {}).items():
        normalized = dict(model)
        entities = normalized.get("entities", {})
        entries = entities.get("entries", {})
        cleaned_patterns: Dict[str, list[Dict[str, Any]]] = {}
        for language, patterns in entries.items():
            cleaned: list[Dict[str, Any]] = []
            for pattern in patterns:
                cleaned.append(
                    {
                        k: v
                        for k, v in pattern.items()
                        if not (k == "alias" and v is None)
                    }
                )
            cleaned_patterns[language] = cleaned
        normalized["entities"] = {"patterns": cleaned_patterns}
        sentiment = normalized.get("sentiment", {})
        lexicon = sentiment.get("lexicon", {})
        languages = lexicon.pop("languages", {})
        for language, spec in languages.items():
            lexicon[language] = {
                "positive": list(spec.get("positive", [])),
                "negative": list(spec.get("negative", [])),
            }
        sentiment["lexicon"] = lexicon
        normalized["sentiment"] = sentiment
        models[key] = normalized
    data["models"] = models
    return data


def _build_database_config(config: Config) -> Dict[str, Any]:
    data = config.database.model_dump(mode="python")
    data["type"] = data.pop("driver")
    if data["type"] == "sqlite":
        data.setdefault("path", Path(data.get("path", "data/news.db")))
    return data


def _build_collection_config(config: Config) -> Dict[str, Any]:
    data = config.collection.model_dump(mode="python")
    data["collection_interval"] = data["collection_interval_hours"]
    data["request_timeout"] = data["request_timeout_seconds"]
    data["circuit_breaker_max_failures"] = data.get("circuit_breaker_max_failures", 3)
    data["circuit_breaker_cooldown_hours"] = data.get(
        "circuit_breaker_cooldown_hours", 4
    )
    return data


def _build_rate_limiting_config(config: Config) -> Dict[str, Any]:
    data = config.rate_limiting.model_dump(mode="python")
    data["delay_between_requests"] = data["delay_between_requests_seconds"]
    data["domain_default_delay"] = data["domain_default_delay_seconds"]
    data["retry_delay"] = data["retry_delay_seconds"]
    return data


def _build_text_processing_config(config: Config) -> Dict[str, Any]:
    data = config.text_processing.model_dump(mode="python")
    data.setdefault("min_title_length", 10)
    data["critic_score_threshold"] = 70
    return data


def _build_logging_config(config: Config) -> Dict[str, Any]:
    return {
        "level": os.environ.get("LOG_LEVEL", config.logging.level),
        "file_path": str(config.logging.file_path),
        "max_file_size": f"{config.logging.max_file_size_mb} MB",
        "retention": f"{config.logging.retention_days} days",
        "format": config.logging.format,
    }


def refresh_runtime_config(config: Any | None = None) -> Any:
    """Reload runtime config and refresh mutable exports in place."""

    global _CONFIG_STATE
    global DATA_DIR, LOGS_DIR, DLQ_DIR
    global ENVIRONMENT, DEBUG, IS_PRODUCTION, IS_STAGING

    cfg = config or load_config()
    _CONFIG_STATE = cfg

    if not isinstance(cfg, Config):
        paths = getattr(cfg, "paths", None)
        if paths is not None:
            DATA_DIR = getattr(paths, "data_dir", DATA_DIR)
            LOGS_DIR = getattr(paths, "logs_dir", LOGS_DIR)
            DLQ_DIR = getattr(paths, "dlq_dir", DLQ_DIR)
            for directory in (DATA_DIR, LOGS_DIR, DLQ_DIR):
                Path(directory).mkdir(parents=True, exist_ok=True)
        app = getattr(cfg, "app", None)
        if app is not None:
            ENVIRONMENT = getattr(app, "environment", ENVIRONMENT)
            DEBUG = getattr(app, "debug", DEBUG)
            IS_PRODUCTION = ENVIRONMENT == "production"
            IS_STAGING = ENVIRONMENT == "staging"
        return cfg

    DATA_DIR = cfg.paths.data_dir
    LOGS_DIR = cfg.paths.logs_dir
    DLQ_DIR = cfg.paths.dlq_dir
    for directory in (DATA_DIR, LOGS_DIR, DLQ_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    ENVIRONMENT = cfg.app.environment
    DEBUG = cfg.app.debug
    IS_PRODUCTION = ENVIRONMENT == "production"
    IS_STAGING = ENVIRONMENT == "staging"

    _replace_mapping(DATABASE_CONFIG, _build_database_config(cfg))
    _replace_mapping(COLLECTION_CONFIG, _build_collection_config(cfg))
    _replace_mapping(RATE_LIMITING_CONFIG, _build_rate_limiting_config(cfg))
    _replace_mapping(ROBOTS_CONFIG, cfg.robots.model_dump(mode="python"))
    _replace_mapping(DEDUP_CONFIG, cfg.dedup.model_dump(mode="python"))
    _replace_mapping(SCORING_CONFIG, cfg.scoring.model_dump(mode="python"))
    _replace_mapping(TEXT_PROCESSING_CONFIG, _build_text_processing_config(cfg))
    _replace_mapping(ENRICHMENT_CONFIG, _normalize_enrichment(cfg))
    _replace_mapping(NEWS_CONFIG, cfg.news.model_dump(mode="python"))
    _replace_mapping(GEMINI_CONFIG, cfg.gemini.model_dump(mode="python"))
    _replace_mapping(LOGGING_CONFIG, _build_logging_config(cfg))

    return cfg


def get_config() -> Any:
    if _CONFIG_STATE is None:
        return refresh_runtime_config()
    return _CONFIG_STATE


def validate_config(config: Config | None = None) -> None:
    """Execute domain specific consistency checks."""

    cfg = config or get_config()
    weights = cfg.scoring.weights
    feature_weights = cfg.scoring.feature_weights
    if (
        abs(
            weights.source_credibility
            + weights.recency
            + weights.content_quality
            + weights.engagement_potential
            - 1.0
        )
        > 0.01
    ):
        raise ConfigError("scoring.weights must sum to 1.0 ±0.01")
    if (
        abs(
            feature_weights.source_credibility
            + feature_weights.freshness
            + feature_weights.content_quality
            + feature_weights.engagement
            - 1.0
        )
        > 0.01
    ):
        raise ConfigError("scoring.feature_weights must sum to 1.0 ±0.01")
    if cfg.database.driver == "sqlite" and not cfg.database.path:
        raise ConfigError("sqlite driver requires database.path")
    if cfg.database.driver == "postgresql":
        missing = [
            field
            for field in ("host", "port", "user", "password")
            if not getattr(cfg.database, field)
        ]
        if missing:
            raise ConfigError("postgresql configuration missing: " + ", ".join(missing))


def set_llm_system_available(value: bool) -> None:
    global LLM_SYSTEM_AVAILABLE
    LLM_SYSTEM_AVAILABLE = value


# Runtime state flags
LLM_SYSTEM_AVAILABLE = True  # Default to True, updated by bootstrap health checks

refresh_runtime_config()

__all__ = [
    "BASE_DIR",
    "CONFIG",
    "DATA_DIR",
    "LOGS_DIR",
    "DLQ_DIR",
    "ENVIRONMENT",
    "DEBUG",
    "IS_PRODUCTION",
    "IS_STAGING",
    "DATABASE_CONFIG",
    "COLLECTION_CONFIG",
    "RATE_LIMITING_CONFIG",
    "ROBOTS_CONFIG",
    "DEDUP_CONFIG",
    "SCORING_CONFIG",
    "TEXT_PROCESSING_CONFIG",
    "ENRICHMENT_CONFIG",
    "NEWS_CONFIG",
    "GEMINI_CONFIG",
    "LOGGING_CONFIG",
    "LLM_SYSTEM_AVAILABLE",
    "get_config",
    "refresh_runtime_config",
    "set_llm_system_available",
    "validate_config",
]
