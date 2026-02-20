Module: news_collector/storage/models.py
Role: Defines the ORM data structures used for persisting articles and sources.
Inputs:
- engine
Outputs:
- Article
- ArticleMetrics
- Dict[str, Any]
- ScoreLog
- Source
- SystemConfig
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- heuristic_scorer
- basic_scorer
- cognitive_scorer
- database
- analytics
- maintenance
- adapters
- api
