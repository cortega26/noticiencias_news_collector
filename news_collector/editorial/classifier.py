"""Determines the public-facing category for an article based on its content."""

from collections.abc import Sequence
from typing import Any, Optional

from noticiencias.config_manager import load_config

from news_collector.config.prompts import build_editorial_classification_system_prompt
from news_collector.editorial.categories import (
    CANONICAL_PUBLIC_CATEGORIES,
    canonicalize_category_label,
)
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class EditorialClassifier:
    """
    Agent responsible for assigning a single editorial category to an article.
    """

    def __init__(self, llm_client: Optional[Any] = None, config: Any | None = None):
        if llm_client is None:
            active_config = config or load_config()
            model = get_model_for_stage(
                "classifier", config=active_config, logger=logger
            )
            self.llm = get_provider(
                config=active_config,
                api_url=active_config.ollama.api_url,
                model=model,
            )
        else:
            self.llm = llm_client

    def try_classify_article(  # noqa: PLR0913
        self,
        title: str,
        summary: str,
        content: str = "",
        *,
        allowed_categories: Sequence[str] | None = None,
        allow_editorial: bool = True,
    ) -> str | None:
        """
        Classifies an article into one public-facing category.
        Returns None if classification fails or the output is invalid.
        """
        allowed = tuple(allowed_categories or CANONICAL_PUBLIC_CATEGORIES)
        valid_categories = set(allowed)
        article_text = f"TITULAR: {title}\n\nRESUMEN: {summary}\n"
        if content:
            # Just a small snippet if available, though prompt relies mostly on core subject
            article_text += f"\nCONTEXTO: {content[:500]}..."

        try:
            response = self.llm.generate_sync(
                prompt=article_text,
                system=build_editorial_classification_system_prompt(
                    allowed_categories=list(allowed),
                    allow_editorial=allow_editorial,
                ),
                json_mode=False,  # We expect a single string token
            )

            if not response or not isinstance(response, str):
                logger.warning(
                    "Editorial Classifier returned empty or invalid response."
                )
                return None

            # Cleaning
            category = canonicalize_category_label(response.rstrip(". "))
            if category in valid_categories:
                return category

            logger.warning(
                f"Editorial Classifier returned invalid category: '{response}'"
            )
            return None

        except Exception as e:
            logger.error(f"Error in Editorial Classifier: {e}")
            return None

    def classify_article(
        self,
        title: str,
        summary: str,
        content: str = "",
        *,
        allowed_categories: Sequence[str] | None = None,
        allow_editorial: bool = True,
    ) -> str:
        """
        Backward-compatible wrapper that fail-closes to CIENCIA.
        """
        return (
            self.try_classify_article(
                title,
                summary,
                content,
                allowed_categories=allowed_categories,
                allow_editorial=allow_editorial,
            )
            or "CIENCIA"
        )
