Module: news_collector/collectors/base_collector.py
Role: Defines the common interface that all data collectors must implement.
Inputs:
- collector_type: str
- logger_factory
- result: Dict[str, Any]
- source_config: Dict[str, Any]
- source_id: str
- sources_config: Dict[str, Dict[str, Any]]
Outputs:
- BaseCollector
- Dict[str, Any]
- Dict[str, float]
- bool
Side effects:
- File I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- ValueError
Used by:
- rss_collector
- headless_collector
- dispatcher
- html_collector
