# Todo — Algorithmic LatAm Filtering and Noise Suppression

- [x] Refine deterministic keywords in `news_collector/scoring/latam_relevance.py`
  - [x] Add regional entities and terms to `LATAM_KEYWORDS`
  - [x] Add corporate cloud, US domestic politics, and academic ML preprint jargon to `LOW_VALUE_KEYWORDS`
- [x] Refine LLM ingestion filtering in `news_collector/scoring/pre_scorer.py`
  - [x] Update `select_top_candidates` LLM prompt with strict down-ranking rules
- [x] Refine Cognitive Scorer in `news_collector/scoring/cognitive_scorer.py`
  - [x] Update `_call_llm_batch` system prompt to specify low scores for corporate tutorials, local politics, and academic preprints
  - [x] Modify `_finalize_score` to load deterministic keywords, adjust `comp_relevance`, and enforce a relevance gate (capping final score at 0.55 if relevance < 0.4)
- [x] Refine Heuristic Scorer in `news_collector/scoring/heuristic_scorer.py`
  - [x] Penalize `LOW_VALUE_KEYWORDS` in `_calculate_latam_affinity`
- [x] Verify Implementation
  - [x] Create verification script `scratch/verify_noise_filtering.py`
  - [x] Run verification script to ensure corporate tutorials and preprints are correctly suppressed while LatAm/global science stories pass
  - [x] Run validation commands: `make lint`, `make type`, `make test`
