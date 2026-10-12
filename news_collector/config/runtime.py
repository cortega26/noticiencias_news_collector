"""Encapsulated runtime settings — single source of truth for mutable config state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class RuntimeSettings:
    """Container for all mutable module-level config state.

    Previously these lived as bare module globals in ``settings.py``.
    Accessible via ``from news_collector.config.settings import RUNTIME``
    or indirectly through module-level compatibility shims.
    """

    # Paths
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    dlq_dir: Path = Path("dlq")

    # Environment — defaults to "unset" (fail closed, plan 123). Only an
    # explicit refresh from config/env may set a real tier; the serving
    # auth gates treat anything but the exact "development" tier as
    # non-development (see is_explicit_development). Never default this to
    # "development": a process that never loaded config would fail OPEN.
    environment: str = "unset"
    debug: bool = False

    # Derived environment flags
    is_production: bool = False
    is_staging: bool = False

    # LLM availability — toggled by bootstrap health checks
    llm_system_available: bool = True

    # Config dicts populated by refresh_runtime_config
    database_config: Dict[str, Any] = field(default_factory=dict)
    collection_config: Dict[str, Any] = field(default_factory=dict)
    rate_limiting_config: Dict[str, Any] = field(default_factory=dict)
    robots_config: Dict[str, Any] = field(default_factory=dict)
    dedup_config: Dict[str, Any] = field(default_factory=dict)
    scoring_config: Dict[str, Any] = field(default_factory=dict)
    text_processing_config: Dict[str, Any] = field(default_factory=dict)
    enrichment_config: Dict[str, Any] = field(default_factory=dict)
    news_config: Dict[str, Any] = field(default_factory=dict)
    gemini_config: Dict[str, Any] = field(default_factory=dict)
    logging_config: Dict[str, Any] = field(default_factory=dict)


def is_explicit_development(environment: object) -> bool:
    """True only for the exact "development" tier (plan 123).

    Unset ("unset"/""/None) and unknown tiers all fail closed: the serving
    auth gates warn-and-serve ONLY on an explicit development tier.
    Deliberately strict (no case/whitespace folding) — a near-miss tier
    name must 503, never fail open.
    """
    return isinstance(environment, str) and environment == "development"
