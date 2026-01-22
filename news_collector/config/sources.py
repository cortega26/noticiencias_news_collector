# config/sources.py
# Catálogo de fuentes RSS para News Collector (Dinámico vía YAML)
# ==============================================================

import yaml
from pathlib import Path
from typing import Any, Dict

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
ELITE_JOURNALS = {}
SCIENCE_MEDIA = {}
INSTITUTIONAL_SOURCES = {}
PREPRINT_SOURCES = {}
COMMUNITY_FEEDS = {}
AI_LABS = {}
ALL_SOURCES = {}

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

        # Reset buckets
        ELITE_JOURNALS = {}
        SCIENCE_MEDIA = {}
        INSTITUTIONAL_SOURCES = {}
        PREPRINT_SOURCES = {}
        COMMUNITY_FEEDS = {}
        AI_LABS = {}
        ALL_SOURCES = {}

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
        yaml.dump(new_sources, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    # Reload globals
    load_sources()

def get_sources_by_category(category):
    return {
        sid: cfg for sid, cfg in ALL_SOURCES.items()
        if cfg.get("category") == category
    }

def get_high_credibility_sources(min_credibility=0.85):
    return {
        sid: cfg for sid, cfg in ALL_SOURCES.items()
        if cfg.get("credibility_score", 0) >= min_credibility
    }

def get_sources_by_update_frequency(frequency):
    return {
        sid: cfg for sid, cfg in ALL_SOURCES.items()
        if cfg.get("update_frequency") == frequency
    }

def validate_sources():
    load_sources() # Ensure fresh check
    required_fields = ["name", "url", "credibility_score", "category", "language"]
    for source_id, source_config in ALL_SOURCES.items():
        for field in required_fields:
            if field not in source_config:
                raise ValueError(f"Fuente {source_id} le falta el campo {field}")

        # Check enabled logic? Not implemented in sources.py natively yet, assuming all active.
    print(f"✅ {len(ALL_SOURCES)} fuentes validadas correctamente")
