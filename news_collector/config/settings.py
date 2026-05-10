"""Project configuration facade backed by noticiencias.config_manager."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from noticiencias.config_manager import Config, ConfigError, load_config

from .runtime import RuntimeSettings

RUNTIME = RuntimeSettings()

_CONFIG_STATE: Any | None = None


class _RuntimeConfigProxy:
    """Stable object reference that always exposes the latest loaded config."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_config(), name)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return repr(get_config())


CONFIG = _RuntimeConfigProxy()

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------
# Backward-compatible shims — resolve reads against RUNTIME so existing
# ``from settings import ENVIRONMENT`` imports keep working without
# changes.  New code should prefer ``from settings import RUNTIME``.
# -----------------------------------------------------------------------

_module_attr_map: Dict[str, str] = {
    "DATA_DIR": "data_dir",
    "LOGS_DIR": "logs_dir",
    "DLQ_DIR": "dlq_dir",
    "ENVIRONMENT": "environment",
    "DEBUG": "debug",
    "IS_PRODUCTION": "is_production",
    "IS_STAGING": "is_staging",
    "DATABASE_CONFIG": "database_config",
    "COLLECTION_CONFIG": "collection_config",
    "RATE_LIMITING_CONFIG": "rate_limiting_config",
    "ROBOTS_CONFIG": "robots_config",
    "DEDUP_CONFIG": "dedup_config",
    "SCORING_CONFIG": "scoring_config",
    "TEXT_PROCESSING_CONFIG": "text_processing_config",
    "ENRICHMENT_CONFIG": "enrichment_config",
    "NEWS_CONFIG": "news_config",
    "GEMINI_CONFIG": "gemini_config",
    "LOGGING_CONFIG": "logging_config",
    "LLM_SYSTEM_AVAILABLE": "llm_system_available",
}


def __getattr__(name: str) -> Any:
    attr = _module_attr_map.get(name)
    if attr is not None:
        return getattr(RUNTIME, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__ + list(_module_attr_map.keys())))
# -----------------------------------------------------------------------


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


# -----------------------------------------------------------------------
# Path / environment / builder resolvers (split from refresh_runtime_config)
# -----------------------------------------------------------------------


def _resolve_paths(cfg: Any) -> None:
    if not isinstance(cfg, Config):
        paths = getattr(cfg, "paths", None)
        if paths is not None:
            RUNTIME.data_dir = getattr(paths, "data_dir", RUNTIME.data_dir)
            RUNTIME.logs_dir = getattr(paths, "logs_dir", RUNTIME.logs_dir)
            RUNTIME.dlq_dir = getattr(paths, "dlq_dir", RUNTIME.dlq_dir)
            for directory in (RUNTIME.data_dir, RUNTIME.logs_dir, RUNTIME.dlq_dir):
                Path(directory).mkdir(parents=True, exist_ok=True)
        return

    RUNTIME.data_dir = cfg.paths.data_dir
    RUNTIME.logs_dir = cfg.paths.logs_dir
    RUNTIME.dlq_dir = cfg.paths.dlq_dir
    for directory in (RUNTIME.data_dir, RUNTIME.logs_dir, RUNTIME.dlq_dir):
        directory.mkdir(parents=True, exist_ok=True)


def _resolve_environment(cfg: Any) -> None:
    if not isinstance(cfg, Config):
        app = getattr(cfg, "app", None)
        if app is not None:
            RUNTIME.environment = getattr(app, "environment", RUNTIME.environment)
            RUNTIME.debug = getattr(app, "debug", RUNTIME.debug)
            RUNTIME.is_production = RUNTIME.environment == "production"
            RUNTIME.is_staging = RUNTIME.environment == "staging"
        return

    RUNTIME.environment = cfg.app.environment
    RUNTIME.debug = cfg.app.debug
    RUNTIME.is_production = RUNTIME.environment == "production"
    RUNTIME.is_staging = RUNTIME.environment == "staging"


def _resolve_builders(cfg: Config) -> None:
    RUNTIME.database_config = _build_database_config(cfg)
    RUNTIME.collection_config = _build_collection_config(cfg)
    RUNTIME.rate_limiting_config = _build_rate_limiting_config(cfg)
    RUNTIME.robots_config = cfg.robots.model_dump(mode="python")
    RUNTIME.dedup_config = cfg.dedup.model_dump(mode="python")
    RUNTIME.scoring_config = cfg.scoring.model_dump(mode="python")
    RUNTIME.text_processing_config = _build_text_processing_config(cfg)
    RUNTIME.enrichment_config = _normalize_enrichment(cfg)
    RUNTIME.news_config = cfg.news.model_dump(mode="python")
    RUNTIME.gemini_config = cfg.gemini.model_dump(mode="python")
    RUNTIME.logging_config = _build_logging_config(cfg)


def refresh_runtime_config(config: Any | None = None) -> Any:
    """Reload runtime config and refresh RUNTIME in place."""
    global _CONFIG_STATE

    cfg = config or load_config()
    _CONFIG_STATE = cfg

    _resolve_paths(cfg)
    _resolve_environment(cfg)

    if isinstance(cfg, Config):
        _resolve_builders(cfg)

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
    """Toggle LLM system availability.

    Deprecated: prefer ``RUNTIME.llm_system_available = value``.
    """
    RUNTIME.llm_system_available = value


# One-shot load on first import
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
    "RUNTIME",
    "get_config",
    "refresh_runtime_config",
    "set_llm_system_available",
    "validate_config",
]
