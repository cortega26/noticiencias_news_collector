Module: news_collector/system/bootstrap.py
Role: Encapsulates runtime dependency construction, system startup logic, and initial health checks.
Inputs:
- collector: Any
- config_override: Dict[str, Any]
- config_override: Optional[Dict[str, Any]]
- db_manager: Any
- health_tracker: Any
- logger: Any
- sources_config: Dict[str, Any]
- system_id: str
Outputs:
- Dict[str, Any]
- List[str]
Side effects:
- Logging
- Network I/O
Invariants:
- LAW-3: System Layer Is Orchestration Only
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
Used by:
- None
