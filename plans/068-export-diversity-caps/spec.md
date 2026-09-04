# Plan 068 — Diversity caps on the export shortlist

## Finding

The publishable shortlist (`data/exports/latest_articles.json`, built by
`system/reporting.py::export_latest_articles`) is raw top-N by score: a
dominant source or topic can fill all 50 slots, and editors get a
monochrome queue. Meanwhile the deterministic, seeded `rerank_articles`
(`news_collector/reranker/reranker.py`, tested, operator-tunable via the
existing `source_cap_percentage` / `topic_cap_percentage` /
`reranker_seed` scoring-config keys) is only applied by `get_top_articles`
— never on the export path that feeds publication. Deduplication itself
already exists upstream (simhash clusters at ingestion), so this plan is
purely about shortlist composition, not identity.

## Design

In `reporting.export_latest_articles`, between fetch and adapt:

1. Fetch `limit * EXPORT_RERANK_OVERSAMPLE` (constant = 3) candidates so
   post-cap output still fills `limit` under realistic concentration
   (extreme single-source dominance still yields fewer — caps working as
   designed, never an error).
2. Build rank dicts via `article.to_dict()` + safely-attached
   `article_metadata` (try/except → `{}` for detached/expired edge cases),
   normalizing `final_score None → 0.0` and `published_date None → ""`
   (the reranker's tie-break tuple would `TypeError` on None).
3. `rerank_articles(..., limit=limit, source_cap_percentage=...,
   topic_cap_percentage=..., seed=...)` with the same
   `scoring_config.get(..., default)` pattern as `get_top_articles`.
4. Map back to ORM by id and `adapt_article_to_export` in reranked order.
   Contract shape unchanged (`article_count == len(models)`).

Non-goals: new scoring components/weights (strict contracts, heavy),
ingestion dedup (exists), `to_dict()` changes (blast radius), new config
keys (caps reuse existing ones), touching `get_top_articles`.

## Verification

- New test: dominant-source + minority seeds with small limit ⇒ minority
  survives, dominant capped at `max(1, limit*cap)`; determinism across
  runs (same seed); empty input ⇒ empty export (no crash).
- Existing export consumers (`test_system_flow`, `test_main_coverage`,
  collection/pipeline boundary suites) green — seeds below caps are
  unaffected by construction.
- `make lint && make type && make test && make test-boundaries`
  (orchestration-adjacent; no contract change).
