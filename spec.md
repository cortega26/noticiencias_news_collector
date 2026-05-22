# Spec: Automatic Re-scoring and Re-ranking of Completed Unpublished Articles

## Goals
- Fix the issue where already scored (vetted) articles are never re-scored or re-ordered, causing their time-decaying scores (like recency) to become stale.
- Automatically re-score and re-rank completed but unpublished articles from the last N days (default 14 days, configurable via `config.toml`) during each collection cycle.
- Leverage the cognitive scorer's built-in caching (`data/cache_cognitive.db`) to ensure that already-scored articles do not hit the LLM API, ensuring near-zero overhead while allowing their freshness/recency decay and final score to be recalculated.
- Protect manually edited metadata: ensure that only `final_score`, `score_components`, and `processing_status` are updated in the database for candidate completed articles, preserving any manual title, summary, category, or tag edits made in Refinery.

## Implementation Details

### 1. Database Repository Updates
In `news_collector/storage/article_repository.py` (and exposed via `news_collector/storage/database.py`):
- Implement `get_completed_articles_for_rescoring(self, days_back: int = 14) -> List[Article]`
- This method queries the database for articles where:
  - `processing_status == "completed"`
  - `published_at` is `None` AND `published_url` is `None` (not yet published)
  - `collected_date >= now() - days_back`
- Ensure all returned articles are expunged from the SQLAlchemy session (to avoid thread/session sharing issues, matching other queries).

### 2. Scoring Coordinator Updates
In `news_collector/scoring/coordinator.py`:
- Retrieve `rescore_days_back` from `SCORING_CONFIG` (default: 14 days).
- In `execute()`:
  - Query new articles pending scoring: `pending_articles = self.db_manager.get_pending_articles(status="validated")`.
  - Query completed articles to be rescored: `completed_articles = self.db_manager.get_completed_articles_for_rescoring(days_back=rescore_days_back)`.
  - Combine both lists into a single list of articles to score.
  - Process them through the scorer as usual.
  - The scorer's cache check will ensure `completed_articles` hit the SQLite cache, fetching cached LLM cognitive dimensions instantly and recalculating time decay.
  - Use `self.db_manager.update_articles_score_bulk()` to update the scores, components, and status of all scored/rescored articles back to the DB.
  - Update `scoring_stats` counters and logs to reflect the number of new articles scored versus existing completed articles rescored.

### 3. Config Updates
In `config.toml`, add under `[scoring]`:
```toml
rescore_days_back = 14
```

## Verification

### Automated Tests
- Run standard validations: `make lint`, `make type`, `make test`.
- Add unit tests in `tests/unit/scoring/test_scoring_coordinator.py` to assert that:
  - `get_completed_articles_for_rescoring` is called.
  - Completed unpublished articles are scored alongside pending ones.
  - The results are saved back via bulk updates.
- Add integration tests in `tests/integration/test_rescoring.py` (or extend an existing integration test) to verify end-to-end database retrieval, caching, time decay recalculation, and database updates.

### Manual Verification
- Verify in Refinery/SQLite that executing the collection/scoring cycle re-scores older unpublished articles.
