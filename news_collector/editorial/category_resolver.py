from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from news_collector.editorial.classifier import EditorialClassifier
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

PUBLIC_CATEGORY_LABELS = {
    "CIENCIA": "Ciencia",
    "SALUD": "Salud",
    "TECNOLOGÍA": "Tecnología",
    "EDITORIAL": "Editorial",
}

GENERIC_CATEGORIES = {
    "",
    "other",
    "unknown",
    "general",
    "science",
    "ciencia",
    "multidisciplinary",
}

DIRECT_CATEGORY_MAP = {
    "health": "Salud",
    "salud": "Salud",
    "medicine": "Salud",
    "medical": "Salud",
    "medicina": "Salud",
    "biology": "Salud",
    "biologia": "Salud",
    "public_health": "Salud",
    "salud_publica": "Salud",
    "technology": "Tecnología",
    "tecnologia": "Tecnología",
    "tech": "Tecnología",
    "artificial_intelligence": "Tecnología",
    "inteligencia_artificial": "Tecnología",
    "ai": "Tecnología",
    "ia": "Tecnología",
    "software": "Tecnología",
    "engineering": "Tecnología",
    "ingenieria": "Tecnología",
    "digital": "Tecnología",
    "editorial": "Editorial",
    "opinion": "Editorial",
    "opinion_piece": "Editorial",
    "analysis": "Editorial",
    "analisis": "Editorial",
    "commentary": "Editorial",
    "comentario": "Editorial",
    "policy": "Editorial",
    "politica": "Editorial",
    "space": "Ciencia",
    "espacio": "Ciencia",
    "physics": "Ciencia",
    "fisica": "Ciencia",
    "chemistry": "Ciencia",
    "quimica": "Ciencia",
    "astronomy": "Ciencia",
    "astronomia": "Ciencia",
    "popular_science": "Ciencia",
    "community_science": "Ciencia",
}


def _normalize_raw_category(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip().casefold()
    if not text:
        return ""

    ascii_text = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in ascii_text if not unicodedata.combining(char))
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    return ascii_text.strip("_")


@dataclass(frozen=True)
class CategoryResolution:
    public_category: str
    selected_raw_category: str | None
    top_level_raw_category: str | None
    metadata_raw_category: str | None
    selected_normalized_category: str
    resolution_method: str


class EditorialCategoryResolver:
    def __init__(self, classifier: EditorialClassifier | None = None):
        self._classifier = classifier

    @property
    def classifier(self) -> EditorialClassifier:
        if self._classifier is None:
            self._classifier = EditorialClassifier()
        return self._classifier

    def resolve_category(
        self,
        *,
        article_id: str,
        title: str,
        summary: str,
        content: str = "",
        raw_category: Any = None,
        metadata_category: Any = None,
    ) -> CategoryResolution:
        selected_raw = (
            raw_category if str(raw_category or "").strip() else metadata_category
        )

        top_level_normalized = _normalize_raw_category(raw_category)
        metadata_normalized = _normalize_raw_category(metadata_category)
        selected_normalized = _normalize_raw_category(selected_raw)

        mapped_selected = DIRECT_CATEGORY_MAP.get(selected_normalized)
        if mapped_selected and selected_normalized not in GENERIC_CATEGORIES:
            return CategoryResolution(
                public_category=mapped_selected,
                selected_raw_category=self._string_or_none(selected_raw),
                top_level_raw_category=self._string_or_none(raw_category),
                metadata_raw_category=self._string_or_none(metadata_category),
                selected_normalized_category=selected_normalized,
                resolution_method="direct_map",
            )

        classifier_result = self.classifier.try_classify_article(
            title=title,
            summary=summary,
            content=content,
        )
        if classifier_result:
            return CategoryResolution(
                public_category=PUBLIC_CATEGORY_LABELS[classifier_result],
                selected_raw_category=self._string_or_none(selected_raw),
                top_level_raw_category=self._string_or_none(raw_category),
                metadata_raw_category=self._string_or_none(metadata_category),
                selected_normalized_category=selected_normalized,
                resolution_method="classifier",
            )

        fallback_category = (
            mapped_selected
            or DIRECT_CATEGORY_MAP.get(top_level_normalized)
            or DIRECT_CATEGORY_MAP.get(metadata_normalized)
            or "Ciencia"
        )

        logger.warning(
            "Category classifier fallback for article %s: top_level=%r metadata=%r normalized=%r fallback=%s"
            % (
                article_id,
                raw_category,
                metadata_category,
                selected_normalized,
                fallback_category,
            )
        )

        return CategoryResolution(
            public_category=fallback_category,
            selected_raw_category=self._string_or_none(selected_raw),
            top_level_raw_category=self._string_or_none(raw_category),
            metadata_raw_category=self._string_or_none(metadata_category),
            selected_normalized_category=selected_normalized,
            resolution_method="fallback",
        )

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
