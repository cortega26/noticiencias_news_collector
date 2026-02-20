Module: news_collector/contracts/validation.py
Role: Defines the payloads for content validation exchanged between system boundaries.
Inputs:
- articles
- content
- context
- id
- published_date
- source_id: str
- summary
- title: str
Outputs:
- ArticleValidationItem
- ArticleValidationPayload
Side effects:
- None explicit
Invariants:
- LAW-1: Data Contracts Are Mandatory
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- None explicit
Used by:
- adapters
