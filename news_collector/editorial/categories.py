from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

CANONICAL_PUBLIC_CATEGORIES = (
    "CIENCIA",
    "SALUD",
    "TECNOLOGÍA",
    "EDITORIAL",
    "ASTRONOMÍA",
    "FÍSICA",
    "QUÍMICA",
    "MATEMÁTICA",
    "BIOLOGÍA",
    "ARQUEOLOGÍA",
)

PUBLIC_CATEGORY_LABELS = {
    "CIENCIA": "Ciencia",
    "SALUD": "Salud",
    "TECNOLOGÍA": "Tecnología",
    "EDITORIAL": "Editorial",
    "ASTRONOMÍA": "Astronomía",
    "FÍSICA": "Física",
    "QUÍMICA": "Química",
    "MATEMÁTICA": "Matemática",
    "BIOLOGÍA": "Biología",
    "ARQUEOLOGÍA": "Arqueología",
}

_NORMALIZED_CANONICAL_LABELS = {
    "CIENCIA": "CIENCIA",
    "SALUD": "SALUD",
    "TECNOLOGIA": "TECNOLOGÍA",
    "EDITORIAL": "EDITORIAL",
    "ASTRONOMIA": "ASTRONOMÍA",
    "FISICA": "FÍSICA",
    "QUIMICA": "QUÍMICA",
    "MATEMATICA": "MATEMÁTICA",
    "BIOLOGIA": "BIOLOGÍA",
    "ARQUEOLOGIA": "ARQUEOLOGÍA",
}

GENERIC_CATEGORIES = {
    "",
    "other",
    "unknown",
    "general",
    "science",
    "ciencia",
    "multidisciplinary",
    "biology",
    "biologia",
    "life_science",
    "life_sciences",
}

GENERIC_SOURCE_CATEGORIES = GENERIC_CATEGORIES | {
    "popular_science",
    "community_science",
}

DIRECT_CATEGORY_MAP = {
    "health": "SALUD",
    "salud": "SALUD",
    "medicine": "SALUD",
    "medical": "SALUD",
    "medicina": "SALUD",
    "public_health": "SALUD",
    "salud_publica": "SALUD",
    "technology": "TECNOLOGÍA",
    "tecnologia": "TECNOLOGÍA",
    "tech": "TECNOLOGÍA",
    "artificial_intelligence": "TECNOLOGÍA",
    "inteligencia_artificial": "TECNOLOGÍA",
    "ai": "TECNOLOGÍA",
    "ia": "TECNOLOGÍA",
    "software": "TECNOLOGÍA",
    "engineering": "TECNOLOGÍA",
    "ingenieria": "TECNOLOGÍA",
    "digital": "TECNOLOGÍA",
    "space": "ASTRONOMÍA",
    "espacio": "ASTRONOMÍA",
    "astronomy": "ASTRONOMÍA",
    "astronomia": "ASTRONOMÍA",
    "astrophysics": "ASTRONOMÍA",
    "astrofisica": "ASTRONOMÍA",
    "physics": "FÍSICA",
    "fisica": "FÍSICA",
    "chemistry": "QUÍMICA",
    "quimica": "QUÍMICA",
    "mathematics": "MATEMÁTICA",
    "math": "MATEMÁTICA",
    "matematica": "MATEMÁTICA",
    "archaeology": "ARQUEOLOGÍA",
    "arqueologia": "ARQUEOLOGÍA",
    "human_evolution": "ARQUEOLOGÍA",
    "editorial": "EDITORIAL",
    "opinion": "EDITORIAL",
    "opinion_piece": "EDITORIAL",
    "analysis": "EDITORIAL",
    "analisis": "EDITORIAL",
    "commentary": "EDITORIAL",
    "comentario": "EDITORIAL",
    "policy": "EDITORIAL",
    "politica": "EDITORIAL",
    "popular_science": "CIENCIA",
    "community_science": "CIENCIA",
}

FIRST_PARTY_HOSTS = {"noticiencias.com", "www.noticiencias.com"}
FIRST_PARTY_SOURCE_IDS = {"noticiencias", "noticiencias_editorial"}
FIRST_PARTY_NAME_PATTERNS = ("noticiencias", "equipo editorial", "equipo de salud")


def normalize_raw_category(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip().casefold()
    if not text:
        return ""

    ascii_text = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in ascii_text if not unicodedata.combining(char))
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    return ascii_text.strip("_")


def is_generic_category(value: Any) -> bool:
    return normalize_raw_category(value) in GENERIC_CATEGORIES


def is_generic_source_category(value: Any) -> bool:
    return normalize_raw_category(value) in GENERIC_SOURCE_CATEGORIES


def canonicalize_category_label(value: str | None) -> str | None:
    if not value:
        return None

    text = unicodedata.normalize("NFKD", str(value).strip().upper())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Z]+", "_", text).strip("_")
    return _NORMALIZED_CANONICAL_LABELS.get(text)


def get_allowed_classifier_categories(*, allow_editorial: bool) -> tuple[str, ...]:
    if allow_editorial:
        return CANONICAL_PUBLIC_CATEGORIES
    return tuple(
        category for category in CANONICAL_PUBLIC_CATEGORIES if category != "EDITORIAL"
    )


def is_first_party_editorial_source(
    *,
    source_url: str | None = None,
    source_name: str | None = None,
    source_id: str | None = None,
) -> bool:
    if source_url:
        host = urlparse(source_url).netloc.casefold()
        if host in FIRST_PARTY_HOSTS:
            return True

    normalized_source_id = normalize_raw_category(source_id)
    if normalized_source_id in FIRST_PARTY_SOURCE_IDS:
        return True

    lowered_name = str(source_name or "").strip().casefold()
    return lowered_name and any(
        pattern in lowered_name for pattern in FIRST_PARTY_NAME_PATTERNS
    )
