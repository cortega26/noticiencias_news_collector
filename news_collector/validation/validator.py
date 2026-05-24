"""
Module role: Orchestrates the validation phase by applying a configured set of rules to collected articles.

Inputs:
- Lists of validation rules (`ValidationRule` instances) provided at initialization.
- Raw collected article data (dictionaries) representing single articles or batches.

Outputs:
- `ValidationResult` indicating success or the specific rule failure reason.
- Dictionary categorizing batches into 'valid' lists and 'invalid' lists with rejection reasons.

Side effects:
- Emits log messages for article rejections during batch validation.

Invariants:
- Fails fast on the first rule violation for single articles.
- Does not mutate the input article payloads during validation.
- Operates on raw dictionary payloads.

Failure modes:
- Returns `ValidationResult(is_valid=False)` instead of raising exceptions when an article fails to meet criteria.
- Missing article fields (e.g., title or content) result in rule-specific decisions (pass or fail) rather than crashes.
"""

from typing import Any, Dict, List

from news_collector.utils.logger import get_logger
from news_collector.validation.rules import (
    BlocklistPatternRule,
    MinContentLengthRule,
    NewsletterContentRule,
    PromptInjectionGuardRule,
    TitleBodyRelevanceRule,
    ValidationResult,
    ValidationRule,
)

# Default patterns to block based on user feedback
DEFAULT_BLOCKLIST = [
    # Newsletter digests
    r"The Download:.*",
    # Shopping, deals, and product promotions
    r"(?i)(big spring sale|prime day|black friday|cyber monday|% off|deal:|best deals|deal of the day|price drop|coupon|voucher|discount code|shopping guide|gift guide|affiliate picks?)",
    # Product buying guides disguised as articles
    r"(?i)(best .+ to buy|buying guide|vs\.\s)",
    # Politics and election coverage outside editorial scope
    r"(?i)(election results|election campaign|campaign trail|candidate debate|presidential race|parliamentary election|midterm results?)",
    # Lifestyle, travel, celebrity, and fashion filler outside editorial scope
    r"(?i)(travel guide|flight deal|hotel deal|packing list|fashion week|red carpet|celebrity style|beauty routine|outfit ideas|dating tips?)",
    # University minutiae irrelevant to general audience
    r"(?i)(named.*fellow|honorary degree|commencement address|class of \d{4}|admitted to the|divestment resolution|AAAS fellow)",
    # Corporate PR / hiring / fundraising
    r"(?i)(is hiring|is laying off|raises \$\d+[MB]|funding round|series [A-D]\b)",
    # Paywalled stubs with no usable content
    r"(?i)^STAT\+:",
]


class ContentValidator:
    """
    Orchestrates article validation using a configured set of rules.
    """

    def __init__(self, rules: List[ValidationRule] | None = None):
        self.logger = get_logger().create_module_logger("news_collector.validation")
        self.rules = rules or self._get_default_rules()

    def _get_default_rules(self) -> List[ValidationRule]:
        return [
            MinContentLengthRule(min_words=50),
            TitleBodyRelevanceRule(min_match_ratio=0.05),  # Very lenient default
            BlocklistPatternRule(patterns=DEFAULT_BLOCKLIST),
            NewsletterContentRule(),
            PromptInjectionGuardRule(),
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
                invalid_articles.append(
                    {
                        "article": article,
                        "reason": result.reason,
                        "rule": result.rule_name,
                    }
                )
                self.logger.info(
                    f"Article rejected: {article.get('title', 'No Title')} - {result.reason}"
                )

        return {"valid": valid_articles, "invalid": invalid_articles}
