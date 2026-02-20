Module: news_collector/contracts/common.py
Role: Provides common shared contract definitions.
Inputs:
- credibility_score
- credibility_score: float
- enrichment
- enrichment: ArticleEnrichment
- fallback: str
- image_source
- image_source: str
- image_status
Outputs:
- ArticleMetadata
- ArticleMetadataModel
- Dict[str, Any]
Side effects:
- None explicit
Invariants:
- LAW-1: Data Contracts Are Mandatory
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- ValueError
Used by:
- collector
