"""
Validation Rules for News Collector
===================================

This module defines the interface and concrete implementations for validation rules
used to filter articles before they enter the scoring phase.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import re

@dataclass
class ValidationResult:
    is_valid: bool
    reason: Optional[str] = None
    rule_name: Optional[str] = None


class ValidationRule(ABC):
    """Abstract base class for all validation rules."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        """
        Validate a single article.
        
        Args:
            article: Dictionary representation of the article (from article.to_dict() + extra fields)
            
        Returns:
            ValidationResult indicating success or failure.
        """
        pass


class MinContentLengthRule(ValidationRule):
    """Rejects articles that are too short to be meaningful."""
    
    def __init__(self, min_words: int = 50):
        self.min_words = min_words

    @property
    def name(self) -> str:
        return "min_content_length"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        content = article.get("content") or article.get("summary") or ""
        # Simple word count approximation
        word_count = len(content.split())
        
        if word_count < self.min_words:
            return ValidationResult(
                is_valid=False,
                reason=f"Content too short ({word_count} words < {self.min_words})",
                rule_name=self.name
            )
        return ValidationResult(is_valid=True, rule_name=self.name)


class TitleBodyRelevanceRule(ValidationRule):
    """
    Checks if the title words appear in the body.
    Very basic heuristic to detect completely mismatched scraping.
    """
    
    def __init__(self, min_match_ratio: float = 0.1):
        self.min_match_ratio = min_match_ratio

    @property
    def name(self) -> str:
        return "title_body_relevance"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        title = article.get("title", "").lower()
        content = (article.get("content") or article.get("summary") or "").lower()
        
        if not title or not content:
            # Cannot validate if missing fields, but let's be permissive here 
            # or aggressive? Let's be permissive and rely on other rules.
            return ValidationResult(is_valid=True, rule_name=self.name)

        title_words = [w for w in re.split(r'\W+', title) if len(w) > 3]
        if not title_words:
            return ValidationResult(is_valid=True, rule_name=self.name)
            
        matches = sum(1 for w in title_words if w in content)
        ratio = matches / len(title_words)
        
        if ratio < self.min_match_ratio:
            return ValidationResult(
                is_valid=False,
                reason=f"Title relevance too low ({ratio:.2f} < {self.min_match_ratio}). Content might be unrelated.",
                rule_name=self.name
            )
            
        return ValidationResult(is_valid=True, rule_name=self.name)


class BlocklistPatternRule(ValidationRule):
    """
    Rejects articles matching specific title patterns known to be problematic.
    """
    
    def __init__(self, patterns: List[str]):
        self.patterns = patterns
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    @property
    def name(self) -> str:
        return "blocklist_pattern"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        title = article.get("title", "")
        
        for i, pattern in enumerate(self._compiled_patterns):
            if pattern.search(title):
                return ValidationResult(
                    is_valid=False,
                    reason=f"Title matches blocklist pattern: '{self.patterns[i]}'",
                    rule_name=self.name
                )
                
        return ValidationResult(is_valid=True, rule_name=self.name)


class NewsletterContentRule(ValidationRule):
    """
    Rejects articles that appear to be full newsletters/digests rather than single articles.
    Newsletters often contain multiple unrelated stories.
    """
    
    PATTERNS = [
        r"today's edition of",
        r"weekday newsletter",
        r"daily dose of",
        r"top stories"
    ]
    
    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.PATTERNS]

    @property
    def name(self) -> str:
        return "newsletter_content_detection"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        content = (article.get("content") or article.get("summary") or "").lower()[:1000] # Check first 1000 chars
        
        for pattern in self._compiled:
            if pattern.search(content):
                return ValidationResult(
                    is_valid=False,
                    reason=f"Content appears to be a newsletter (matched '{pattern.pattern}').",
                    rule_name=self.name
                )
        return ValidationResult(is_valid=True, rule_name=self.name)
