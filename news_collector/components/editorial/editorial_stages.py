"""
Module role: Typed cache identities for the EditorAgent publication stages.

Owns:
- EditorialStage: the cache-key enum used by `EditorAgent._get_cache_path`

Does NOT own:
- Cache storage/reading (EditorAgent)
- Stage execution, retry policy or provider provenance (future Phase 7c stages)

The enum values are cache-key strings. A versioned key intentionally starts a
new stage checkpoint while leaving earlier artifacts untouched; change a key
only when the stage's behavior must be rerun for cached articles.
"""

from __future__ import annotations

from enum import StrEnum


class EditorialStage(StrEnum):
    """Cache identity of each EditorAgent stage artifact."""

    TRANSLATION = "stage1_translation_evidence_v2"
    EDITORIAL = "stage2_editorial_evidence_v2"
    TECHNICAL_CRITIC_OK = "stage2_5_critic_evidence_v2_ok"
    EDITORIAL_CRITIC_OK = "stage2_6_editorial_critic_evidence_v5_ok"
    HEADLINE_CRITIC_REVIEW = "stage3_headline_critic_evidence_v1_review"
    ENRICHMENT = "stage4_enrichment_evidence_v2"
