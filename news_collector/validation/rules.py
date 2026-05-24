"""
Module role: Defines the abstract interface and concrete implementations for validation rules to filter articles before scoring.

Inputs:
- Configuration parameters for rules (e.g., minimum words, match ratios, blocklist patterns).
- Raw article dictionaries containing fields like 'title', 'content', 'summary', and 'content_mode'.

Outputs:
- `ValidationResult` objects indicating whether the article passed (`is_valid`) and tracking the `reason` and `rule_name` if it failed.

Side effects:
- None.

Invariants:
- Concrete rules must implement the `name` property and `validate` method.
- Rules do not mutate article dictionary payloads.
- Permissive handling of missing fields: missing titles or content typically fail safely or pass gracefully depending on the specific rule logic.

Failure modes:
- Returns `ValidationResult(is_valid=False)` when an article fails the configured criteria (e.g., too short, low relevance, or matches a blocklist).
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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

        if article.get("content_mode") in ("summary_only", "summary_fallback"):
            min_words = 20  # Relaxed limit for summaries
        else:
            min_words = self.min_words

        if word_count < min_words:
            return ValidationResult(
                is_valid=False,
                reason=f"Content too short ({word_count} words < {min_words})",
                rule_name=self.name,
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

        # Skip strict relevance check for summaries (they often miss keywords)
        if article.get("content_mode") in ("summary_only", "summary_fallback"):
            return ValidationResult(is_valid=True, rule_name=self.name)

        title_words = [w for w in re.split(r"\W+", title) if len(w) > 3]
        if not title_words:
            return ValidationResult(is_valid=True, rule_name=self.name)

        matches = sum(1 for w in title_words if w in content)
        ratio = matches / len(title_words)

        if ratio < self.min_match_ratio:
            return ValidationResult(
                is_valid=False,
                reason=f"Title relevance too low ({ratio:.2f} < {self.min_match_ratio}). Content might be unrelated.",
                rule_name=self.name,
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
                    rule_name=self.name,
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
        r"top stories",
    ]

    def __init__(self):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.PATTERNS]

    @property
    def name(self) -> str:
        return "newsletter_content_detection"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        content = (article.get("content") or article.get("summary") or "").lower()[
            :1000
        ]  # Check first 1000 chars

        for pattern in self._compiled:
            if pattern.search(content):
                return ValidationResult(
                    is_valid=False,
                    reason=f"Content appears to be a newsletter (matched '{pattern.pattern}').",
                    rule_name=self.name,
                )
        return ValidationResult(is_valid=True, rule_name=self.name)


class PromptInjectionGuardRule(ValidationRule):
    """
    Detects and rejects articles containing potential prompt injection payloads
    while allowing legitimate news articles or security advisories that explain
    or discuss these vulnerabilities.
    """

    TRIGGERS = [
        r"(?i)\bignore\s+(?:previous|all|the|prior)\s+instructions\b",
        r"(?i)\bignora\s+(?:las\s+)?(?:instrucciones|órdenes)\s+(?:anteriores|previas)\b",
        r"(?i)\bforget\s+(?:my\s+)?(?:previous|all|prior)\s+instructions\b",
        r"(?i)\bolvida\s+(?:las\s+)?(?:instrucciones|reglas)\s+(?:anteriores|previas)\b",
        r"(?i)\bsystem\s+prompt\b",
        r"(?i)\bprompt\s+del\s+sistema\b",
        r"(?i)\bstop\s+translating\b",
        r"(?i)\bdeja\s+de\s+traducir\b",
        r"(?i)\bno\s+traduzcas\b",
        r"(?i)\bignore\s+the\s+text\s+(?:above|below)\b",
        r"(?i)\bignora\s+el\s+texto\s+(?:de\s+)?(?:arriba|abajo)\b",
        r"(?i)\bnew\s+instruction\b",
        r"(?i)\bnueva\s+instrucción\b",
        r"(?i)\[system\b",
        r"(?i)\[instruction\b",
    ]

    EXEMPTIONS = [
        "prompt injection",
        "inyección de prompt",
        "inyección indirecta",
        "jailbreak",
        "jailbreaking",
        "cybersecurity",
        "ciberseguridad",
        "security vulnerability",
        "vulnerabilidad de seguridad",
        "security researcher",
        "investigador de seguridad",
        "investigadores de seguridad",
        "threat intelligence",
        "inteligencia de amenazas",
        "google threat intelligence",
        "red team",
        "equipo rojo",
        "vulnerabilities",
        "vulnerabilidades",
        "common crawl",
        "adversarial",
        "adversario",
        "ciberataque",
        "cyberattack",
        "google security",
        "security blog",
        "investigador",
        "investigadores",
    ]

    def __init__(self) -> None:
        self._compiled_triggers = [re.compile(p) for p in self.TRIGGERS]
        # Pre-compile exemptions as lowercase strings for faster check
        self._lowercase_exemptions = [e.lower() for e in self.EXEMPTIONS]

    @property
    def name(self) -> str:
        return "prompt_injection_guard"

    def validate(self, article: Dict[str, Any]) -> ValidationResult:
        title = article.get("title") or ""
        content = article.get("content") or ""
        summary = article.get("summary") or ""

        # Concatenate text to analyze
        full_text = f"{title}\n{content}\n{summary}"
        full_text_lower = full_text.lower()

        # Check triggers
        matched_trigger = None
        for pattern in self._compiled_triggers:
            match = pattern.search(full_text)
            if match:
                matched_trigger = match.group(0)
                break

        if matched_trigger:
            # Check for exemptions
            has_exemption = False
            for exemption in self._lowercase_exemptions:
                if exemption in full_text_lower:
                    has_exemption = True
                    break

            if has_exemption:
                # Potential injection trigger but it's a security/news discussion
                return ValidationResult(is_valid=True, rule_name=self.name)
            else:
                return ValidationResult(
                    is_valid=False,
                    reason=f"Potential prompt injection detected (matched pattern: '{matched_trigger}').",
                    rule_name=self.name,
                )

        return ValidationResult(is_valid=True, rule_name=self.name)
