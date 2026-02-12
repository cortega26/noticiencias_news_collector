import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Set, TypedDict

import yaml
from pydantic import BaseModel, Field


class NormalizeResult(BaseModel):
    """Result of a tag normalization operation."""
    tags: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    replaced: List[Dict[str, str]] = Field(default_factory=list)
    merged: List[Dict[str, str]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TagNormalizer:
    """Ensures consistent, deduplicated, and limit-compliant tags."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Default to tags.yml in the same directory
            config_path = str(Path(__file__).parent / "tags.yml")
        
        self.config = self._load_config(config_path)
        self.stop_tags = set(self.config.get("stop_tags", []))
        self.alias_map = self.config.get("alias_map", {})
        self.whitelist_short = set(self.config.get("whitelist_short", []))
        self.max_tags = self.config.get("max_tags_per_article", 8)

    def _load_config(self, path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _strip_accents(self, text: str) -> str:
        """Remove accents from text."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', text)
            if unicodedata.category(c) != 'Mn'
        )

    def _basic_norm(self, tag: str) -> str:
        """Apply basic normalization rules."""
        tag = tag.strip().lower()
        tag = re.sub(r"[-_]", " ", tag)
        tag = re.sub(r"\s+", " ", tag)
        return tag

    def _dedupe_key(self, tag: str) -> str:
        """Generate a key for deduplication."""
        t = self._basic_norm(tag)
        t = self._strip_accents(t)
        return t

    def normalize_tags(self, tags: List[str]) -> NormalizeResult:
        """
        Normalize a list of tags.
        
        Steps:
        1. Basic normalization
        2. Remove junk/stop tags
        3. Apply alias map
        4. Deduplicate (near-match detection)
        5. Enforce max count
        """
        cleaned: List[str] = []
        removed: List[str] = []
        replaced: List[Dict[str, str]] = []
        merged: List[Dict[str, str]] = []
        warnings: List[str] = []

        # Step 1-3: Basic norm, filtering, aliasing
        for t in tags:
            t0 = self._basic_norm(t)

            if not t0 or t0 in self.stop_tags:
                removed.append(t)
                continue

            if len(t0) < 3 and t0 not in self.whitelist_short:
                removed.append(t)
                continue
            
            # Check if length > 40
            if len(t0) > 40:
                 removed.append(t)
                 continue

            t1 = self.alias_map.get(t0, t0)

            if t1 != t0:
                replaced.append({"from": t0, "to": t1})

            cleaned.append(t1)

        # Step 4: Deduplication
        deduped: Dict[str, str] = {}

        for t in cleaned:
            k = self._dedupe_key(t)

            if k not in deduped:
                deduped[k] = t
            else:
                existing = deduped[k]
                # Prefer existing if shorter or same length (stable choice)
                # Actually, spec says: "best = min(existing, t, key=len)"
                # "Prefer: aliased tags, shorter tags, stable topics"
                
                # If lengths are different, pick shortest. 
                # If lengths are same, we keep 'existing' (first seen) for stability.
                if len(t) < len(existing):
                    best = t
                    dropped = existing
                else:
                    best = existing
                    dropped = t

                deduped[k] = best
                merged.append({
                    "kept": best,
                    "dropped": dropped
                })

        final = sorted(list(deduped.values()))

        # Step 5: Max count enforcement
        if len(final) > self.max_tags:
            warnings.append(f"tag count exceeded max ({self.max_tags}); truncated")
            final = final[:self.max_tags]
            
        # Final safety check for "other" (should be caught by stop_tags but per spec)
        if "other" in final:
            final.remove("other")
            warnings.append("removed forbidden tag: other")

        return NormalizeResult(
            tags=final,
            removed=removed,
            replaced=replaced,
            merged=merged,
            warnings=warnings
        )
