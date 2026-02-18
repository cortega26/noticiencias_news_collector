# A1 Business Logic and Correctness Report
Last updated: 2026-01-02

## Scope
- c:\Users\corte\VS Code Projects\noticiencias_news_collector

## Critical journeys reviewed
1) Collector run: RSS fetch -> enrichment -> scoring -> persist -> data/exports/latest_articles.json
2) Refinery publish: admin selects article -> LLM refinement -> write _posts -> PR creation

## Evidence reviewed
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\collectors\rss_collector.py
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\storage\database.py
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\news_collector\storage\models.py
- c:\Users\corte\VS Code Projects\noticiencias_news_collector\apps\refinery\main.py

## Findings (logged in ledger)
- F-0006 (S2): Concurrent inserts can bypass content-hash dedupe.
- F-0007 (S2): Slug collisions can overwrite existing posts in PR branch.

## Notes
- URL canonicalization is applied before persistence, reducing duplicate URLs.
- Database migrations are applied at startup; schema alignment is generally safe.
- Processed-article tracking is local to refinery.db, so dedupe is per runner.

## Recommended next steps
1) Add a uniqueness guard for content-hash dedupe, or use a canonical URL hash.
2) Ensure filename collisions are handled when writing to `_posts`.
