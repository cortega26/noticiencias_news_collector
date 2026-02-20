Module: news_collector/contracts/export.py
Role: Defines data contracts used for system export operations.
Inputs:
- article_count: int
- articles
- authors
- category
- collected_date
- components
- content
- contract
Outputs:
- ExportArticleModel
- ExportContractV2
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
