Module: news_collector/contracts/adapters.py
Role: Adapts safely between raw ORM or system objects and validated Pydantic contracts.
Inputs:
- article: Any
- article: Article
- articles: List[Any]
- source_config
Outputs:
- ArticleScoringData
- ArticleValidationPayload
- ExportArticleModel
- ScoringInputModel
Side effects:
- None explicit
Invariants:
- LAW-1: Data Contracts Are Mandatory
- LAW-2: Adapters Are the Only Conversion Layer
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- None
