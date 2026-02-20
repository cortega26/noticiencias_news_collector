Module: news_collector/observability/enrichment_metrics_store.py
Role: Stores and aggregates metrics from the enrichment pipeline strategies.
Inputs:
- content_length: int
- duration: float
- headless_seconds: float
- is_publishable: bool
- proxy_requests: int
- reason: str
- source_id: str
- strategy: str
Outputs:
- Dict[str, Dict[str, Any]]
- EnrichmentMetricsStore
- Optional[Dict[str, Any]]
- ProductionReadonlyStore
Side effects:
- File I/O
- Logging
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
Used by:
- strategy_lock_manager
- strategy_optimizer
- router
- proxy_manager
