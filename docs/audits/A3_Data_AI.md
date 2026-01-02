# A3 Data and AI Lineage
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector

## Data lineage (high level)
1) RSS sources -> collector parse/enrichment -> SQLite/Postgres.
2) Scored articles -> JSON export (latest_articles.json).
3) Refinery consumes export -> LLM rewrite -> Jekyll posts -> public site.

## Evidence reviewed
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\run_collector.py
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\contracts
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\storage\models.py
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\apps\refinery\main.py

## Findings (logged in ledger)
- F-0010 (S2): Export JSON lacks schema/version metadata.

## AI usage notes
- LLM refinement in `apps/refinery` is prompt-driven and human-reviewed.
- No explicit evaluation harness or drift tracking is defined for LLM output.

## Recommended next steps
1) Add schema versioning metadata to JSON exports.
2) Document scoring metric definitions and ownership in a metrics catalog.
