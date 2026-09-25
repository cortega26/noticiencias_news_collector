"""
Module role: Typed cache identities for the EditorAgent publication stages.

Owns:
- EditorialStage: the cache-key enum used by `EditorAgent._get_cache_path`

Does NOT own:
- Cache storage/reading (EditorAgent)
- Stage execution, retry policy or provider provenance (future Phase 7c stages)

The enum values are the historical cache-key strings; changing one without a
cache migration silently orphans existing artifacts.
"""

from __future__ import annotations

from enum import StrEnum


class EditorialStage(StrEnum):
    """Cache identity of each EditorAgent stage artifact."""

    TRANSLATION = "stage1_translation"
    EDITORIAL = "stage2_editorial"
    TECHNICAL_CRITIC_OK = "stage2_5_critic_ok"
    EDITORIAL_CRITIC_OK = "stage2_6_editorial_critic_ok"
    ENRICHMENT = "stage4_enrichment"
