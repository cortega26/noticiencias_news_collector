"""
Editorial Classifier Module
===========================

Determines the public-facing category (badge) for an article based on its content impact.
"""

from typing import Any, Optional

from news_collector.config.prompts import EDITORIAL_CLASSIFICATION_SYSTEM_PROMPT
from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)
VALID_CATEGORIES = {"CIENCIA", "SALUD", "TECNOLOGÍA", "EDITORIAL"}


class EditorialClassifier:
    """
    Agent responsible for assigning a single editorial category to an article.
    Categories: CIENCIA, SALUD, TECNOLOGÍA, EDITORIAL.
    """

    def __init__(self, llm_client: Optional[Any] = None):
        if llm_client is None:
            model = get_model_for_stage("classifier", config=CONFIG, logger=logger)
            self.llm = get_provider(
                config=CONFIG, api_url=CONFIG.ollama.api_url, model=model
            )
        else:
            self.llm = llm_client

    def try_classify_article(
        self, title: str, summary: str, content: str = ""
    ) -> str | None:
        """
        Classifies an article into one of the 4 editorial categories.
        Returns None if classification fails or the output is invalid.
        """
        article_text = f"TITULAR: {title}\n\nRESUMEN: {summary}\n"
        if content:
            # Just a small snippet if available, though prompt relies mostly on core subject
            article_text += f"\nCONTEXTO: {content[:500]}..."

        try:
            response = self.llm.generate_sync(
                prompt=article_text,
                system=EDITORIAL_CLASSIFICATION_SYSTEM_PROMPT,
                json_mode=False,  # We expect a single string token
            )

            if not response or not isinstance(response, str):
                logger.warning(
                    "Editorial Classifier returned empty or invalid response."
                )
                return None

            # Cleaning
            category = response.strip().upper()

            # Handle potential extra punctuation (e.g. "SALUD.")
            if category.endswith("."):
                category = category[:-1]

            if category in VALID_CATEGORIES:
                return category

            logger.warning(
                f"Editorial Classifier returned invalid category: '{category}'"
            )
            return None

        except Exception as e:
            logger.error(f"Error in Editorial Classifier: {e}")
            return None

    def classify_article(self, title: str, summary: str, content: str = "") -> str:
        """
        Backward-compatible wrapper that fail-closes to CIENCIA.
        """
        return self.try_classify_article(title, summary, content) or "CIENCIA"
