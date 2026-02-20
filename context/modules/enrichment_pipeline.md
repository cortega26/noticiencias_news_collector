Module: news_collector/enrichment/pipeline.py
Role: Manages the deterministic article enrichment pipeline for extracting multilingual entities, topics, and sentiment.
Inputs:
- article
Outputs:
- EnrichmentPipeline
- MutableMapping[str, object]
- str
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- None
