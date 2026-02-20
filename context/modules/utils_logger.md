Module: news_collector/utils/logger.py
Role: Configures the robust and elegant application-wide logging system.
Inputs:
- config: Optional[Dict[str, Any]]
- config_summary: Optional[Dict[str, Any]]
- context: Optional[Dict[str, Any]]
- context: str
- error: Exception
- func
- logger_instance
- metrics: Dict[str, Any]
Outputs:
- Any
- CollectionSessionLogger
- NewsCollectorLogger
Side effects:
- File I/O
- Logging
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- ImportError
Used by:
- policy
- ai_editor
- auditor
- github_publisher
- rss_collector
- base_collector
- html_collector
- provider
