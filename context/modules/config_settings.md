Module: news_collector/config/settings.py
Role: Provides the project configuration facade backed by Pydantic settings.
Inputs:
- config
Outputs:
- None explicit
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- ConfigError
Used by:
- logger
- basic_scorer
- database
- collector
- ai_editor
- rss_collector
- rate_limit_utils
- base_collector
- html_collector
- pipeline
- http_client
- requests_client
- bootstrap
- activity_monitor
