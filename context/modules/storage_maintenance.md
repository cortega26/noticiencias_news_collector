Module: news_collector/storage/maintenance.py
Role: Provides maintenance helpers for database cleanup and health checks.
Inputs:
- days_to_keep: int
- db_type: str
- session: Session
Outputs:
- Dict[str, Any]
Side effects:
- Database I/O
- Network I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- database
