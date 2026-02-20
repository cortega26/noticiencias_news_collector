Module: news_collector/enrichment/router.py
Role: Decides and executes the appropriate enrichment strategy for a given article.
Inputs:
- candidate: Dict[str, Any]
- source_config: Dict[str, Any]
- source_id: str
Outputs:
- Dict[str, Any]
- EnrichmentStrategyRouter
Side effects:
- File I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- rss_collector
