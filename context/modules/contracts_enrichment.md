Module: news_collector/contracts/enrichment.py
Role: Defines contracts for enrichment pipeline payloads.
Inputs:
- content: str
- editorial_display_category
- editorial_display_category: str
- entities
- language
- language: str
- model_version: str
- normalized_summary: str
Outputs:
- ArticleEnrichment
- ArticleEnrichmentModel
- ArticleForEnrichment
- ArticleForEnrichmentModel
Side effects:
- None explicit
Invariants:
- LAW-1: Data Contracts Are Mandatory
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- ValueError
Used by:
- common
