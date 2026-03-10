"""
Editorial Classifier Module
===========================

Determines the public-facing category (badge) for an article based on its content impact.
"""

from typing import Optional

from news_collector.config.prompts import EDITORIAL_CLASSIFICATION_SYSTEM_PROMPT
from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


class EditorialClassifier:
    """
    Agent responsible for assigning a single editorial category to an article.
    Categories: CIENCIA, SALUD, TECNOLOGÍA, EDITORIAL.
    """

    def __init__(self, llm_client: Optional[OllamaProvider] = None):
        if llm_client is None:
            model = get_model_for_stage("classifier", config=CONFIG, logger=logger)
            self.llm = OllamaProvider(api_url=CONFIG.ollama.api_url, model=model)
        else:
            self.llm = llm_client

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
            )

            if not response or not isinstance(response, str):
                logger.warning("Editorial Classifier returned empty or invalid response.")
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
