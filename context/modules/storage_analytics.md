Module: news_collector/storage/analytics.py
Role: Provides analytics helpers for database reporting.
Inputs:
- buckets: int
- date
- days: int
- days_back: int
- db_type: str
- session: Session
Outputs:
- Dict[str, Any]
- Dict[str, int]
- List[Dict[str, Any]]
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
