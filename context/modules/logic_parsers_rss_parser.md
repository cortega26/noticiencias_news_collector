Module: news_collector/logic/parsers/rss_parser.py
Role: Parses RSS feeds and extracts standardized article metadata.
Inputs:
- content: Union[str, bytes]
- parsed_feed
- source_config: Dict[str, Any]
Outputs:
- Any
- List[Dict[str, Any]]
- RssParser
- bool
Side effects:
- None explicit
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
Used by:
- rss_collector
