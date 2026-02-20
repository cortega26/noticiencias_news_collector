Module: news_collector/utils/text_cleaner.py
Role: Provides utilities for cleaning and sanitizing extracted raw text.
Inputs:
- html: str
- text: str
Outputs:
- str
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
Used by:
- dedupe
- rss_parser
- base_collector
- nlp_stack
- pipeline
