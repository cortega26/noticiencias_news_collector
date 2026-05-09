from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from news_collector.editorial.categories import (
    DIRECT_CATEGORY_MAP,
    GENERIC_CATEGORIES,
    PUBLIC_CATEGORY_LABELS,
    get_allowed_classifier_categories,
    is_first_party_editorial_source,
    is_generic_source_category,
    normalize_raw_category,
)
from news_collector.editorial.classifier import EditorialClassifier
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


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
        source_url: str | None = None,
        source_name: str | None = None,
        source_id: str | None = None,
    ) -> CategoryResolution:
        raw_text = str(raw_category or "").strip()
        metadata_text = str(metadata_category or "").strip()
        selected_raw = (
            metadata_category
            if raw_text and is_generic_source_category(raw_category) and metadata_text
            else (raw_category if raw_text else metadata_category)
        )

        top_level_normalized = normalize_raw_category(raw_category)
        metadata_normalized = normalize_raw_category(metadata_category)
        selected_normalized = normalize_raw_category(selected_raw)
        allow_editorial = is_first_party_editorial_source(
            source_url=source_url,
            source_name=source_name,
            source_id=source_id,
        )
        allowed_categories = get_allowed_classifier_categories(
            allow_editorial=allow_editorial
        )

        mapped_selected = DIRECT_CATEGORY_MAP.get(selected_normalized)
        if (
            mapped_selected
            and selected_normalized not in GENERIC_CATEGORIES
            and (mapped_selected != "EDITORIAL" or allow_editorial)
        ):
            return CategoryResolution(
                public_category=PUBLIC_CATEGORY_LABELS[mapped_selected],
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
            allowed_categories=allowed_categories,
            allow_editorial=allow_editorial,
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
            (
                mapped_selected
                if mapped_selected != "EDITORIAL" or allow_editorial
                else None
            )
            or (
                DIRECT_CATEGORY_MAP.get(top_level_normalized)
                if DIRECT_CATEGORY_MAP.get(top_level_normalized) != "EDITORIAL"
                or allow_editorial
                else None
            )
            or (
                DIRECT_CATEGORY_MAP.get(metadata_normalized)
                if DIRECT_CATEGORY_MAP.get(metadata_normalized) != "EDITORIAL"
                or allow_editorial
                else None
            )
            or "CIENCIA"
        )

        logger.warning(
            "Category classifier fallback for article %s: top_level=%r metadata=%r normalized=%r fallback=%s"
            % (
                article_id,
                raw_category,
                metadata_category,
                selected_normalized,
                PUBLIC_CATEGORY_LABELS[fallback_category],
            )
        )

        return CategoryResolution(
            public_category=PUBLIC_CATEGORY_LABELS[fallback_category],
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
