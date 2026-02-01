"""
Editorial Classifier Module
===========================

Determines the public-facing category (badge) for an article based on its content impact.
"""

import logging
from typing import Optional

from news_collector.config.prompts import EDITORIAL_CLASSIFICATION_SYSTEM_PROMPT
from news_collector.infrastructure.llm.provider import OllamaProvider

logger = logging.getLogger(__name__)


class EditorialClassifier:
    """
    Agent responsible for assigning a single editorial category to an article.
    Categories: CIENCIA, SALUD, TECNOLOGÍA, EDITORIAL.
    """

    def __init__(self, llm_client: Optional[OllamaProvider] = None):
        self.llm = llm_client or OllamaProvider()

    def classify_article(self, title: str, summary: str, content: str = "") -> str:
        """
        Classifies an article into one of the 4 editorial categories.
        Returns "CIENCIA" as default fallback if classification fails.
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
                temperature=0.0,  # Deterministic
            )

            if not response:
                logger.warning("Editorial Classifier returned empty response.")
                return "CIENCIA"

            # Cleaning
            category = response.strip().upper()

            # Simple validation against known set
            valid_categories = {"CIENCIA", "SALUD", "TECNOLOGÍA", "EDITORIAL"}

            # Handle potential extra punctuation (e.g. "SALUD.")
            if category.endswith("."):
                category = category[:-1]

            if category in valid_categories:
                return category

            logger.warning(
                f"Editorial Classifier returned invalid category: '{category}'"
            )
            return "CIENCIA"

        except Exception as e:
            logger.error(f"Error in Editorial Classifier: {e}")
            return "CIENCIA"
