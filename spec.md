# Spec: Algorithmic LatAm Filtering and Noise Suppression

## Goals
- Enhance the filtering and scoring of articles in the news collector to prioritize stories with either a direct Latin American (LatAm) connection or universal public-interest science value.
- Suppress irrelevant content (specifically, commercial developer tutorials, US local/regional politics/court battles, and highly academic computer science preprints) without relying on Spanish-language sources.
- Prevent low-value content from being downloaded/scraped (Ingestion gate) and scored high (Scoring gate).

## Implementation Details

### 1. Heuristics & Keywords
In `news_collector/scoring/latam_relevance.py`:
- Add regional universities, research bodies, geography, and LatAm specific health/scientific terms to `LATAM_KEYWORDS`.
- Add keywords indicating developer/cloud tutorials, US domestic political campaigns/agencies, and theoretical preprints to `LOW_VALUE_KEYWORDS`.

### 2. Ingestion Filtering (PreScorer)
In `news_collector/scoring/pre_scorer.py`:
- Refine the LLM prompt in `select_top_candidates` to explicitly instruct the LLM to down-rank/reject commercial product/developer tutorials, niche academic computer science preprints, and US domestic/local politics.

### 3. Cognitive & Heuristic Scoring
In `news_collector/scoring/cognitive_scorer.py`:
- Refine the LLM prompt in `_call_llm_batch` under the relevance criteria to instruct the LLM to score corporate cloud tutorials, niche computer science preprints, and US local/domestic political controversies low (0-1 stars).
- Modify `_finalize_score` to run deterministic checks using expanded `LOW_VALUE_KEYWORDS` and `LATAM_KEYWORDS` from `latam_relevance.py`.
- Adjust `comp_relevance` deterministically:
  - If `LOW_VALUE_KEYWORDS` is present and no `LATAM_KEYWORDS` is present, penalize relevance.
  - If `LATAM_KEYWORDS` is present, boost relevance.
- Enforce a strict relevance gate: if `comp_relevance < 0.4` (corresponding to LLM relevance score < 2.0 / 5.0), cap the final score to `0.55` (forces discard/under the 0.60 inclusion threshold).

In `news_collector/scoring/heuristic_scorer.py`:
- Update `_calculate_latam_affinity` to return `0.0` if `LOW_VALUE_KEYWORDS` are found.

## Verification
- Run standard backend validation suite: `make lint`, `make type`, `make test`.
- Create a test script `scratch/verify_noise_filtering.py` to evaluate scorer output on a test dataset containing a mixture of target articles.
