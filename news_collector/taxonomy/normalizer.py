import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import BaseModel, Field

# Setup logger
logger = logging.getLogger(__name__)


class NormalizeResult(BaseModel):
    """Result of a tag normalization operation."""

    tags: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    replaced: List[Dict[str, str]] = Field(default_factory=list)
    merged: List[Dict[str, str]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Result of a tag validation operation."""

    is_valid: bool
    needs_review: bool
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class TagNormalizer:
    """
    Ensures consistent, deduplicated, and limit-compliant tags.
    Implements the 'Sanitizer' contract: low-level, mechanical fixes.
    """

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Default to tags.yml in the same directory
            base_path = Path(__file__).parent
            config_path = str(base_path / "tags.yml")
            ortho_path = str(base_path / "orthography.yml")
        else:
            config_p = Path(config_path)
            config_path = str(config_p)
            ortho_path = str(config_p.parent / "orthography.yml")

        self.config = self._load_config(config_path)
        self.ortho_config = self._load_config(ortho_path)

        self.stop_tags = set(self.config.get("stop_tags", []))
        self.alias_map = self.config.get("alias_map", {})
        self.orthography = self.ortho_config.get("corrections", {})
        self.whitelist_short = set(self.config.get("whitelist_short", []))
        self.max_tags = self.config.get("max_tags_per_article", 8)
        self.min_length = self.config.get("min_tag_length", 3)
        self.max_length = self.config.get("max_tag_length", 40)

        # Regex for allowed chars: lowercase, numbers, accents, spaces
        # Corresponds to: "^[a-z0-9áéíóúüñ\s]+$"
        self.allowed_chars_pattern = re.compile(
            self.config.get("allowed_chars_regex", r"^[a-z0-9áéíóúüñ\s]+$")
        )

    def _load_config(self, path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _strip_accents(self, text: str) -> str:
        """Remove accents from text (for dedupe key generation)."""
        return "".join(
            c
            for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )

    def _basic_sanitize(self, tag: str) -> str:
        """
        Mechanical sanitization:
        - Strip whitespace
        - Lowercase
        - Replace hyphens/underscores with spaces
        - Collapse multiple spaces
        """
        if not isinstance(tag, str):
            tag = str(tag)

        tag = tag.strip().lower()
        tag = re.sub(r"[-_]", " ", tag)
        tag = re.sub(r"\s+", " ", tag)
        return tag

    def sanitize_tags(self, tags: List[str]) -> NormalizeResult:
        """
        Main entry point for sanitization.
        Follows the contract:
        1. Sanitize string (lower, trim, replace)
        2. Orthography correction
        3. Semantic aliasing
        4. Deduplication
        5. Stop-tag filtering
        """
        cleaned: List[str] = []
        removed: List[str] = []
        replaced: List[Dict[str, str]] = []
        merged: List[Dict[str, str]] = []
        warnings: List[str] = []

        # Pass 1: Transformation
        for t in tags:
            original = t
            t_sanitized = self._basic_sanitize(t)

            # Empty check
            if not t_sanitized:
                removed.append(original)
                continue

            # Stop tags check (early)
            if t_sanitized in self.stop_tags:
                removed.append(t_sanitized)
                warnings.append(f"removed stop tag: {t_sanitized}")
                continue

            # Orthography
            if t_sanitized in self.orthography:
                new_t = self.orthography[t_sanitized]
                if new_t != t_sanitized:
                    replaced.append({"from": t_sanitized, "to": new_t})
                    t_sanitized = new_t

            # Semantics (Alias)
            if t_sanitized in self.alias_map:
                new_t = self.alias_map[t_sanitized]
                if new_t != t_sanitized:
                    replaced.append({"from": t_sanitized, "to": new_t})
                    t_sanitized = new_t

            cleaned.append(t_sanitized)

        # Pass 2: Deduplication
        # Strategy: Use a canonical key (stripped accents) to find collisions.
        # If collision, prefer the one that is already in 'cleaned' (first wins? or specific rule?)
        # Actually, if we have "energía oscura" and "energia oscura", we want "energía oscura" if it exists.
        # Current logic: First occurrence wins unless a "better" one is found later?
        # Simpler: First occurrence wins. The input order matters.

        unique_map: Dict[str, str] = {}  # Key -> Tag
        final_list: List[str] = []

        for t in cleaned:
            # Dedupe key: strictly lower char (already lower), no accents
            key = self._strip_accents(t)

            if key in unique_map:
                existing = unique_map[key]
                if existing != t:
                    # Near duplicate found
                    merged.append({"kept": existing, "dropped": t})
            else:
                unique_map[key] = t
                final_list.append(t)

        # Pass 3: Final Filtering (Length constraints)
        result_tags = []
        for t in final_list:
            if len(t) < self.min_length and t not in self.whitelist_short:
                removed.append(t)
                warnings.append(f"removed short tag: {t}")
                continue
            if len(t) > self.max_length:
                removed.append(t)
                warnings.append(f"removed long tag: {t}")
                continue
            result_tags.append(t)

        # Max tags Limit
        if len(result_tags) > self.max_tags:
            warnings.append(f"truncated tags to max {self.max_tags}")
            result_tags = result_tags[: self.max_tags]

        return NormalizeResult(
            tags=result_tags,
            removed=removed,
            replaced=replaced,
            merged=merged,
            warnings=warnings,
        )

    def validate_tags(self, tags: List[str]) -> ValidationResult:
        """
        Validates a list of tags against the strict contract.
        Should run AFTER sanitization.
        Returns validation result with 'needs_review' flag if manual intervention is required.
        """
        warnings = []
        errors = []
        is_valid = True
        needs_review = False

        if len(tags) > self.max_tags:
            # This should have been handled by sanitizer, but if not, it's a warning
            warnings.append(f"Tag count ({len(tags)}) exceeds limit ({self.max_tags})")

        for t in tags:
            # Check characters (Must be strictly allowed regex)
            if not self.allowed_chars_pattern.match(t):
                errors.append(f"Invalid characters in tag: '{t}'")
                needs_review = True
                is_valid = False

            # Check forbidden words (Redundant check but safety)
            if t in self.stop_tags:
                errors.append(f"Forbidden stop tag found: '{t}'")
                needs_review = True
                is_valid = False

            # Check length (Redundant)
            if len(t) < self.min_length and t not in self.whitelist_short:
                errors.append(f"Tag too short: '{t}'")
                is_valid = False

            if len(t) > self.max_length:
                errors.append(f"Tag too long: '{t}'")
                is_valid = False

        return ValidationResult(
            is_valid=is_valid,
            needs_review=needs_review,
            warnings=warnings,
            errors=errors,
        )
