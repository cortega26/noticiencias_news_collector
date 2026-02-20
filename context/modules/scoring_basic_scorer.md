Module: news_collector/scoring/basic_scorer.py
Role: Evaluates articles across dimensions like credibility, recency, and quality to compute a final score.
Inputs:
- article: Article
- articles: List[Article]
- scorer: BasicScorer
- source_config: Dict[str, Any]
Outputs:
- BasicScorer
- Dict[str, Any]
- SafeNamespace
Side effects:
- Logging
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- TypeError
- ValidationError
- ValueError
Used by:
- cognitive_scorer
