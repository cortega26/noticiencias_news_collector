Module: news_collector/storage/database.py
Role: Manages connections, pooling, and CRUD operations for articles and sources.
Inputs:
- article_data
- article_id
- article_id: int
- articles_data: List[Union[Dict[str, Any], CollectorArticleModel]]
- batch_size: int
- buckets: int
- category: str
- connection_record
Outputs:
- DatabaseManager
- Dict[str, Any]
- Dict[str, Optional[str]]
- Dict[str, int]
- List[Article]
- List[Dict[str, Any]]
- Optional[Article]
- Optional[Dict[str, Any]]
Side effects:
- Database I/O
- Logging
- Network I/O
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- IntegrityError
- TypeError
- ValidationError
- ValueError
Used by:
- refinery_engine
- base_collector
- api
