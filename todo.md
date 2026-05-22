# Todo — Automatic Re-scoring and Re-ranking of Completed Unpublished Articles

- [x] Run baseline verification to ensure existing tests pass
- [x] Implement `get_completed_articles_for_rescoring` in `news_collector/storage/article_repository.py`
- [x] Expose `get_completed_articles_for_rescoring` in `news_collector/storage/database.py`
- [x] Update `config.toml` to add `rescore_days_back = 14` under `[scoring]`
- [ ] Update `news_collector/scoring/coordinator.py` to retrieve and score both new and completed unpublished articles
- [ ] Create unit tests in `tests/unit/scoring/test_scoring_coordinator.py` for the rescoring behavior
- [ ] Create integration tests in `tests/integration/test_rescoring.py` (or extend database integration tests) to verify the DB and scoring pipeline rescoring end-to-end
- [ ] Run full verification suite (`make lint`, `make type`, `make test`)
