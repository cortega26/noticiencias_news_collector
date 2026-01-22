"""
Content Validator Module
========================

Orchestrates the validation phase by applying a set of rules to collected articles.
"""

from typing import Any, Dict, List
import logging

from news_collector.validation.rules import (
    ValidationRule,
    ValidationResult,
    MinContentLengthRule,
    TitleBodyRelevanceRule,
    BlocklistPatternRule,
    NewsletterContentRule
)

# Default patterns to block based on user feedback
DEFAULT_BLOCKLIST = [
    r"The Download:.*",  # Matches "The Download: cut through AI coding hype..."
]

class ContentValidator:
    """
    Orchestrates article validation using a configured set of rules.
    """

    def __init__(self, rules: List[ValidationRule] = None):
        self.logger = logging.getLogger("news_collector.validation")
        self.rules = rules or self._get_default_rules()

    def _get_default_rules(self) -> List[ValidationRule]:
        return [
            MinContentLengthRule(min_words=50),
            TitleBodyRelevanceRule(min_match_ratio=0.05), # Very lenient default
            BlocklistPatternRule(patterns=DEFAULT_BLOCKLIST),
            NewsletterContentRule()
        ]

    def validate_article(self, article: Dict[str, Any]) -> ValidationResult:
        """
        Validates a single article against all configured rules.
        Fails fast on the first rule violation.
        """
        for rule in self.rules:
            result = rule.validate(article)
            if not result.is_valid:
                return result

        return ValidationResult(is_valid=True)

    def validate_batch(self, articles: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
        """
        Validates a list of articles.

        Returns:
            Dict containing:
            - 'valid': List of valid articles
            - 'invalid': List of tuples (article, reason)
        """
        valid_articles = []
        invalid_articles = []

        for article in articles:
            result = self.validate_article(article)
            if result.is_valid:
                valid_articles.append(article)
            else:
                invalid_articles.append({
                    "article": article,
                    "reason": result.reason,
                    "rule": result.rule_name
                })
                self.logger.info(f"Article rejected: {article.get('title', 'No Title')} - {result.reason}")

        return {
            "valid": valid_articles,
            "invalid": invalid_articles
        }
