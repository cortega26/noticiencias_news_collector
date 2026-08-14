"""Project configuration facade backed by noticiencias.config_manager."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from noticiencias.config_manager import Config, ConfigError, load_config

from .runtime import RuntimeSettings


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """Immutable, versioned snapshot of all runtime configuration.

    Each successful ``refresh_runtime_config()`` creates a fresh snapshot
    with a monotonic version number.  Consumers should call
    ``get_runtime_config()`` at the boundary of each operation / pipeline
    cycle to obtain the current values.

    Dict fields are deep-copied when the snapshot is built, so callers
    cannot accidentally mutate a shared reference.
    """

    version: int
    data_dir: Path
    logs_dir: Path
    dlq_dir: Path
    environment: str
    debug: bool
    is_production: bool
    is_staging: bool
    llm_system_available: bool
    database_config: Dict[str, Any]
    collection_config: Dict[str, Any]
    rate_limiting_config: Dict[str, Any]
    robots_config: Dict[str, Any]
    dedup_config: Dict[str, Any]
    scoring_config: Dict[str, Any]
    text_processing_config: Dict[str, Any]
    enrichment_config: Dict[str, Any]
    news_config: Dict[str, Any]
    gemini_config: Dict[str, Any]
    logging_config: Dict[str, Any]
    build_timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    restart_required_keys: frozenset[str] = field(default_factory=frozenset)
    changed_keys: frozenset[str] = field(default_factory=frozenset)


RUNTIME = RuntimeSettings()

_CONFIG_STATE: Any | None = None

_CONFIG_VERSION: int = 0
_CURRENT_SNAPSHOT: RuntimeConfigSnapshot | None = None


class _RuntimeConfigProxy:
    """Stable object reference that always exposes the latest loaded config."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_config(), name)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return repr(get_config())


CONFIG = _RuntimeConfigProxy()

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------
# Backward-compatible shims (DEPRECATED — migrate to get_runtime_config())
#
# These resolve reads against RUNTIME so that ``settings.COLLECTION_CONFIG``
# (attribute access on the module) stays live.  However, *by-value* imports
# such as ``from settings import COLLECTION_CONFIG`` capture the value at
# import time and will NOT see refreshes.
#
# New and migrated code should call ``get_runtime_config()`` at the start
# of each operation / pipeline cycle and read from the returned snapshot.
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


def _build_snapshot_from_runtime() -> RuntimeConfigSnapshot:
    """Build a frozen snapshot from the current RUNTIME values.

    Dict fields are deep-copied so that callers cannot mutate the
    snapshot's internal state.
    """
    global _CONFIG_VERSION
    _CONFIG_VERSION += 1

    return RuntimeConfigSnapshot(
        version=_CONFIG_VERSION,
        data_dir=RUNTIME.data_dir,
        logs_dir=RUNTIME.logs_dir,
        dlq_dir=RUNTIME.dlq_dir,
        environment=RUNTIME.environment,
        debug=RUNTIME.debug,
        is_production=RUNTIME.is_production,
        is_staging=RUNTIME.is_staging,
        llm_system_available=RUNTIME.llm_system_available,
        database_config=copy.deepcopy(RUNTIME.database_config),
        collection_config=copy.deepcopy(RUNTIME.collection_config),
        rate_limiting_config=copy.deepcopy(RUNTIME.rate_limiting_config),
        robots_config=copy.deepcopy(RUNTIME.robots_config),
        dedup_config=copy.deepcopy(RUNTIME.dedup_config),
        scoring_config=copy.deepcopy(RUNTIME.scoring_config),
        text_processing_config=copy.deepcopy(RUNTIME.text_processing_config),
        enrichment_config=copy.deepcopy(RUNTIME.enrichment_config),
        news_config=copy.deepcopy(RUNTIME.news_config),
        gemini_config=copy.deepcopy(RUNTIME.gemini_config),
        logging_config=copy.deepcopy(RUNTIME.logging_config),
    )


def _diff_keys(
    old: RuntimeConfigSnapshot | None,
    new: RuntimeConfigSnapshot,
) -> tuple[frozenset[str], frozenset[str]]:
    """Compare two snapshots and return (changed_keys, restart_required_keys).

    restart_required_keys captures settings whose runtime change cannot
    be effected without a process restart (e.g. database driver/URL).
    """
    if old is None:
        return frozenset(), frozenset()

    config_dict_keys = (
        "database_config",
        "collection_config",
        "rate_limiting_config",
        "robots_config",
        "dedup_config",
        "scoring_config",
        "text_processing_config",
        "enrichment_config",
        "news_config",
        "gemini_config",
        "logging_config",
    )
    scalar_keys = (
        "data_dir",
        "logs_dir",
        "dlq_dir",
        "environment",
        "debug",
        "is_production",
        "is_staging",
        "llm_system_available",
    )

    restart_candidates = frozenset({"database_config"})

    changed: set[str] = set()
    restart: set[str] = set()

    for key in config_dict_keys:
        old_val = getattr(old, key)
        new_val = getattr(new, key)
        if old_val != new_val:
            changed.add(key)
            if key in restart_candidates:
                restart.add(key)

    for key in scalar_keys:
        old_val = getattr(old, key)
        new_val = getattr(new, key)
        if old_val != new_val:
            changed.add(key)

    return frozenset(changed), frozenset(restart)


def refresh_runtime_config(config: Any | None = None) -> RuntimeConfigSnapshot:
    """Reload runtime config, refresh RUNTIME, and atomically swap snapshot.

    Builds all configuration, runs validation, then atomically commits a
    new ``RuntimeConfigSnapshot``.  If validation fails the current
    snapshot and RUNTIME state are left untouched (rollback-safe).

    Returns the new snapshot on success.
    """
    global _CONFIG_STATE, _CONFIG_VERSION, _CURRENT_SNAPSHOT

    cfg = config or load_config()

    # Validate BEFORE touching RUNTIME so a failed refresh leaves every
    # legacy RUNTIME/CONFIG field untouched too, not just the snapshot.
    if isinstance(cfg, Config):
        validate_config(cfg)

    _resolve_paths(cfg)
    _resolve_environment(cfg)

    if isinstance(cfg, Config):
        _resolve_builders(cfg)

    # Only a real Config may become _CONFIG_STATE: get_config() callers
    # (validate_config, bootstrap) walk .scoring/.github/etc. attributes.
    # Test doubles and partial stand-ins passed as `config` must not
    # overwrite the canonical state (pytest-randomly surfaced this when a
    # SimpleNamespace leaked into _CONFIG_STATE and broke the e2e harness's
    # next initialize()).
    if isinstance(cfg, Config):
        _CONFIG_STATE = cfg

    old_snapshot = _CURRENT_SNAPSHOT
    new_snapshot = _build_snapshot_from_runtime()
    changed, restart = _diff_keys(old_snapshot, new_snapshot)

    object.__setattr__(new_snapshot, "changed_keys", changed)
    object.__setattr__(new_snapshot, "restart_required_keys", restart)

    _CURRENT_SNAPSHOT = new_snapshot

    return new_snapshot


def get_runtime_config() -> RuntimeConfigSnapshot:
    """Return the current immutable runtime configuration snapshot.

    Lazily triggers a one-shot refresh on first call.
    """
    global _CURRENT_SNAPSHOT
    if _CURRENT_SNAPSHOT is None:
        refresh_runtime_config()
    assert _CURRENT_SNAPSHOT is not None
    return _CURRENT_SNAPSHOT


def get_config() -> Any:
    if _CONFIG_STATE is None:
        refresh_runtime_config()
    return _CONFIG_STATE


def validate_config(config: Config | None = None) -> None:
    """Execute domain specific consistency checks."""
    cfg = config or get_config()
    # get_config() may return a RuntimeConfigSnapshot (which exposes
    # scoring_config, not scoring) when called during bootstrap paths that
    # never set _CONFIG_STATE. Resolve the underlying Config so the
    # consistency checks operate on the real sections (2026-08-12, surfaced
    # by pytest-randomly in the smoke test).
    scoring_section = getattr(cfg, "scoring", None)
    if scoring_section is None:
        scoring_section = getattr(cfg, "scoring_config", None)
    if scoring_section is None:
        raise ConfigError(
            "Runtime config is missing the 'scoring' section; "
            "re-run refresh_runtime_config() with a complete config.toml"
        )
    weights = scoring_section.weights
    feature_weights = scoring_section.feature_weights
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
    "BASE_DIR",  # noqa: F822
    "CONFIG",  # noqa: F822
    "DATA_DIR",  # noqa: F822
    "LOGS_DIR",  # noqa: F822
    "DLQ_DIR",  # noqa: F822
    "ENVIRONMENT",  # noqa: F822
    "DEBUG",  # noqa: F822
    "IS_PRODUCTION",  # noqa: F822
    "IS_STAGING",  # noqa: F822
    "DATABASE_CONFIG",  # noqa: F822
    "COLLECTION_CONFIG",  # noqa: F822
    "RATE_LIMITING_CONFIG",  # noqa: F822
    "ROBOTS_CONFIG",  # noqa: F822
    "DEDUP_CONFIG",  # noqa: F822
    "SCORING_CONFIG",  # noqa: F822
    "TEXT_PROCESSING_CONFIG",  # noqa: F822
    "ENRICHMENT_CONFIG",  # noqa: F822
    "NEWS_CONFIG",  # noqa: F822
    "GEMINI_CONFIG",  # noqa: F822
    "LOGGING_CONFIG",  # noqa: F822
    "LLM_SYSTEM_AVAILABLE",  # noqa: F822
    "RUNTIME",  # noqa: F822
    "RuntimeConfigSnapshot",  # noqa: F822
    "get_config",  # noqa: F822
    "get_runtime_config",  # noqa: F822
    "refresh_runtime_config",  # noqa: F822
    "set_llm_system_available",  # noqa: F822
    "validate_config",  # noqa: F822
]
