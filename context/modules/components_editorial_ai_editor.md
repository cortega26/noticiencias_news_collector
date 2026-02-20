Module: news_collector/components/editorial/ai_editor.py
Role: Modifies and refines article content using LLM integrations.
Inputs:
- article_content: str
- benefit: str
- direct: str
- excerpt: str
- override_date: str
- question: str
- raw_text
- tags
Outputs:
- EditorAgent
- HeadlinesSchema
- dict
- str
Side effects:
- File I/O
- Logging
Invariants:
- LAW-4: Canonical Identity Is Immutable
- LAW-5: Canonical URLs Are Deterministic & Immutable
Failure modes:
- Exception
- ImportError
- ValidationError
- ValueError
Used by:
- refinery_engine
