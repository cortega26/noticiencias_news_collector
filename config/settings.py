"""Project configuration facade backed by noticiencias.config_manager."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from noticiencias.config_manager import Config, ConfigError, load_config

CONFIG: Config = load_config()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = CONFIG.paths.data_dir
LOGS_DIR = CONFIG.paths.logs_dir
DLQ_DIR = CONFIG.paths.dlq_dir

for directory in (DATA_DIR, LOGS_DIR, DLQ_DIR):
    directory.mkdir(parents=True, exist_ok=True)

ENVIRONMENT = CONFIG.app.environment
DEBUG = CONFIG.app.debug
IS_PRODUCTION = ENVIRONMENT == "production"
IS_STAGING = ENVIRONMENT == "staging"

DATABASE_CONFIG: Dict[str, Any] = CONFIG.database.model_dump(mode="python")
DATABASE_CONFIG["type"] = DATABASE_CONFIG.pop("driver")
if DATABASE_CONFIG["type"] == "sqlite":
    DATABASE_CONFIG.setdefault("path", Path(DATABASE_CONFIG.get("path", "data/news.db")))

COLLECTION_CONFIG: Dict[str, Any] = CONFIG.collection.model_dump(mode="python")
COLLECTION_CONFIG["collection_interval"] = COLLECTION_CONFIG["collection_interval_hours"]
COLLECTION_CONFIG["request_timeout"] = COLLECTION_CONFIG["request_timeout_seconds"]

RATE_LIMITING_CONFIG: Dict[str, Any] = CONFIG.rate_limiting.model_dump(mode="python")
RATE_LIMITING_CONFIG["delay_between_requests"] = RATE_LIMITING_CONFIG[
    "delay_between_requests_seconds"
]
RATE_LIMITING_CONFIG["domain_default_delay"] = RATE_LIMITING_CONFIG[
    "domain_default_delay_seconds"
]
RATE_LIMITING_CONFIG["retry_delay"] = RATE_LIMITING_CONFIG["retry_delay_seconds"]

ROBOTS_CONFIG: Dict[str, Any] = CONFIG.robots.model_dump(mode="python")
DEDUP_CONFIG: Dict[str, Any] = CONFIG.dedup.model_dump(mode="python")
SCORING_CONFIG: Dict[str, Any] = CONFIG.scoring.model_dump(mode="python")
TEXT_PROCESSING_CONFIG: Dict[str, Any] = CONFIG.text_processing.model_dump(mode="python")

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
                cleaned.append({k: v for k, v in pattern.items() if not (k == "alias" and v is None)})
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


ENRICHMENT_CONFIG: Dict[str, Any] = _normalize_enrichment(CONFIG)
NEWS_CONFIG: Dict[str, Any] = CONFIG.news.model_dump(mode="python")

LOGGING_CONFIG: Dict[str, Any] = {
    "level": CONFIG.logging.level,
    "file_path": str(CONFIG.logging.file_path),
    "max_file_size": f"{CONFIG.logging.max_file_size_mb} MB",
    "retention": f"{CONFIG.logging.retention_days} days",
    "format": CONFIG.logging.format,
}


def validate_config(config: Config | None = None) -> None:
    """Execute domain specific consistency checks."""

    cfg = config or CONFIG
    weights = cfg.scoring.weights
    feature_weights = cfg.scoring.feature_weights
    if abs(
        weights.source_credibility
        + weights.recency
        + weights.content_quality
        + weights.engagement_potential
        - 1.0
    ) > 0.01:
        raise ConfigError("scoring.weights must sum to 1.0 ±0.01")
    if abs(
        feature_weights.source_credibility
        + feature_weights.freshness
        + feature_weights.content_quality
        + feature_weights.engagement
        - 1.0
    ) > 0.01:
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
            raise ConfigError(
                "postgresql configuration missing: " + ", ".join(missing)
            )


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
    "LOGGING_CONFIG",
    "validate_config",
]
