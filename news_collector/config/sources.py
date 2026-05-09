# config/sources.py
# Catálogo de fuentes RSS para News Collector (Dinámico vía YAML)
# ==============================================================

from pathlib import Path
from typing import Any, Dict

import yaml

# Configuración de categorías (se mantiene estática por ahora)
CATEGORY_CONFIG = {
    "multidisciplinary": {
        "priority_multiplier": 1.0,
        "min_score_threshold": 0.3,
        "max_daily_articles": 15,
    },
    "medicine": {
        "priority_multiplier": 1.2,
        "min_score_threshold": 0.4,
        "max_daily_articles": 12,
    },
    "artificial_intelligence": {
        "priority_multiplier": 1.1,
        "min_score_threshold": 0.35,
        "max_daily_articles": 10,
    },
    "technology": {
        "priority_multiplier": 1.0,
        "min_score_threshold": 0.3,
        "max_daily_articles": 8,
    },
    "space": {
        "priority_multiplier": 0.9,
        "min_score_threshold": 0.3,
        "max_daily_articles": 6,
    },
    "biology": {
        "priority_multiplier": 0.95,
        "min_score_threshold": 0.3,
        "max_daily_articles": 8,
    },
    "popular_science": {
        "priority_multiplier": 0.8,
        "min_score_threshold": 0.25,
        "max_daily_articles": 5,
    },
    "community_science": {
        "priority_multiplier": 0.6,
        "min_score_threshold": 0.2,
        "max_daily_articles": 4,
    },
}

# Globals to be populated
ELITE_JOURNALS: Dict[str, Any] = {}
SCIENCE_MEDIA: Dict[str, Any] = {}
INSTITUTIONAL_SOURCES: Dict[str, Any] = {}
PREPRINT_SOURCES: Dict[str, Any] = {}
COMMUNITY_FEEDS: Dict[str, Any] = {}
AI_LABS: Dict[str, Any] = {}
ALL_SOURCES: Dict[str, Any] = {}


def load_sources():
    """Carga las fuentes desde sources.yaml y popula las variables globales."""
    global ELITE_JOURNALS, SCIENCE_MEDIA, INSTITUTIONAL_SOURCES, PREPRINT_SOURCES, COMMUNITY_FEEDS, AI_LABS, ALL_SOURCES

    current_dir = Path(__file__).parent
    yaml_path = current_dir / "sources.yaml"

    if not yaml_path.exists():
        # Fallback or error? For now, empty or raise
        print(f"Warning: {yaml_path} not found. using empty sources.")
        return

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Preserve dict identities so existing imports see live updates.
        ELITE_JOURNALS.clear()
        SCIENCE_MEDIA.clear()
        INSTITUTIONAL_SOURCES.clear()
        PREPRINT_SOURCES.clear()
        COMMUNITY_FEEDS.clear()
        AI_LABS.clear()
        ALL_SOURCES.clear()

        for source_id, config in data.items():
            # Populate ALL_SOURCES
            # Ensure cache fields exist
            config.setdefault("etag", None)
            config.setdefault("last_modified", None)

            ALL_SOURCES[source_id] = config

            # Bucketing by group
            group = config.get("_group")
            if group == "ELITE_JOURNALS":
                ELITE_JOURNALS[source_id] = config
            elif group == "SCIENCE_MEDIA":
                SCIENCE_MEDIA[source_id] = config
            elif group == "INSTITUTIONAL_SOURCES":
                INSTITUTIONAL_SOURCES[source_id] = config
            elif group == "PREPRINT_SOURCES":
                PREPRINT_SOURCES[source_id] = config
            elif group == "COMMUNITY_FEEDS":
                COMMUNITY_FEEDS[source_id] = config
            elif group == "AI_LABS":
                AI_LABS[source_id] = config

    except Exception as e:
        print(f"Error loading sources.yaml: {e}")


# Initial Load
load_sources()


# Helper Functions
def save_sources(new_sources: Dict[str, Any]):
    """Guarda el diccionario completo de fuentes en sources.yaml"""
    current_dir = Path(__file__).parent
    yaml_path = current_dir / "sources.yaml"

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            new_sources,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    # Reload globals
    load_sources()


def get_sources_by_category(category):
    return {
        sid: cfg for sid, cfg in ALL_SOURCES.items() if cfg.get("category") == category
    }


def get_high_credibility_sources(min_credibility=0.85):
    return {
        sid: cfg
        for sid, cfg in ALL_SOURCES.items()
        if cfg.get("credibility_score", 0) >= min_credibility
    }


def get_sources_by_update_frequency(frequency):
    return {
        sid: cfg
        for sid, cfg in ALL_SOURCES.items()
        if cfg.get("update_frequency") == frequency
    }


# Tier Definitions
TIER_A_INTERVAL = 600  # 10 mins (Range 300-900)
TIER_B_INTERVAL = 3600  # 1 hour (Range 1800-3600)
TIER_C_INTERVAL = 21600  # 6 hours
TIER_D_INTERVAL = 86400  # 24 hours (Manual/Restricted)

VALID_TIERS = ["A", "B", "C", "D"]


def validate_sources():  # noqa: C901
    """
    Validates that all sources conform to the strict High-Reliability Source Onboarding Protocol.
    Raises ValueError if any source is invalid.
    """
    load_sources()  # Ensure fresh check
    required_fields = [
        "name",
        "url",
        "credibility_score",
        "category",
        "tier",
        "fetchability_score",
        "crawl_interval_seconds",
    ]

    errors = []

    for source_id, config in ALL_SOURCES.items():
        # 1. Check required fields
        for field in required_fields:
            if field not in config:
                errors.append(f"Source '{source_id}' missing required field: '{field}'")

        # 2. Check Tier Validity
        tier = config.get("tier")
        if tier and tier not in VALID_TIERS:
            errors.append(
                f"Source '{source_id}' has invalid tier: '{tier}'. Must be one of {VALID_TIERS}"
            )

        # 3. Check Fetchability Score
        f_score = config.get("fetchability_score")
        if f_score is not None and (
            not isinstance(f_score, (int, float)) or not (0 <= f_score <= 100)
        ):
            errors.append(
                f"Source '{source_id}' has invalid fetchability_score: {f_score}. Must be 0-100."
            )

        # 4. Check Interval
        interval = config.get("crawl_interval_seconds")
        if interval is not None and (not isinstance(interval, int) or interval <= 0):
            errors.append(
                f"Source '{source_id}' has invalid crawl_interval_seconds: {interval}. Must be positive int."
            )

        # 5. Check Enrichment Strategy
        strategy = config.get(
            "enrichment_strategy", "http"
        )  # Default to http if missing
        valid_strategies = [
            "scholarly",
            "http",
            "headless_fallback",
            "scrapling_stealth",
            "scrapling_http",
            "discovery_only",
        ]
        if strategy not in valid_strategies:
            errors.append(
                f"Source '{source_id}' has invalid enrichment_strategy: '{strategy}'. Must be one of {valid_strategies}"
            )

        # 6. Check Headless Configuration
        if strategy in ("headless_fallback", "scrapling_stealth"):
            if not isinstance(config.get("headless_enabled"), bool):
                errors.append(
                    f"Source '{source_id}' must specify 'headless_enabled' (bool) when using headless_fallback."
                )

            max_seconds = config.get("headless_max_seconds")
            if max_seconds is not None and (
                not isinstance(max_seconds, int) or max_seconds <= 0
            ):
                errors.append(
                    f"Source '{source_id}' has invalid headless_max_seconds: {max_seconds}. Must be positive int."
                )

        errors.extend(audit_source_strategy_consistency(source_id, config))

    if errors:
        error_msg = (
            f"❌ Configuration Validation Failed ({len(errors)} errors):\n"
            + "\n".join([f"  - {e}" for e in errors])
        )
        raise ValueError(error_msg)

    print(
        f"✅ {len(ALL_SOURCES)} sources validated successfully against strict schema."
    )


def get_sources_by_tier(tier: str) -> Dict[str, Any]:
    """Retrieve sources belonging to a specific tier (A, B, C, D)."""
    return {sid: cfg for sid, cfg in ALL_SOURCES.items() if cfg.get("tier") == tier}


def audit_source_strategy_consistency(
    source_id: str, config: Dict[str, Any]
) -> list[str]:
    """Return deterministic consistency warnings for source strategy choices."""
    issues: list[str] = []
    strategy = str(config.get("enrichment_strategy", "http")).strip().lower()
    content_mode = str(config.get("content_mode", "full_text")).strip().lower()
    fetch_mode = str(config.get("fetch_mode", "")).strip().lower()
    justification = str(config.get("strategy_justification", "")).strip()

    if strategy == "scrapling_stealth" and not config.get("headless_enabled"):
        issues.append(
            f"Source '{source_id}' uses scrapling_stealth but headless_enabled is false."
        )

    if (
        strategy in {"scrapling_stealth", "headless_fallback"}
        and content_mode in {"summary_only", "summary_fallback"}
        and not justification
    ):
        issues.append(
            f"Source '{source_id}' uses {strategy} with {content_mode} but lacks strategy_justification."
        )

    if (
        strategy in {"scrapling_stealth", "headless_fallback"}
        and fetch_mode == "rss_only"
        and not justification
    ):
        issues.append(
            f"Source '{source_id}' is rss_only but still uses {strategy} without strategy_justification."
        )

    if strategy == "scrapling_stealth" and config.get("headless_enabled") is False:
        issues.append(
            f"Source '{source_id}' cannot use scrapling_stealth while headless is disabled."
        )

    return issues


def collect_source_strategy_audit(
    sources: Dict[str, Any] | None = None,
) -> Dict[str, list[str]]:
    """Audit the configured source catalog and return only sources with warnings."""
    audited = sources or ALL_SOURCES
    return {
        source_id: issues
        for source_id, config in audited.items()
        if (issues := audit_source_strategy_consistency(source_id, config))
    }
