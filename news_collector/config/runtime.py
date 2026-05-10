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

    # Environment
    environment: str = "development"
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
