"""Tests for ValidationCoordinator — extracted from NewsCollectorSystem._execute_validation."""

from unittest.mock import MagicMock

import pytest

from news_collector.validation.coordinator import ValidationCoordinator


class _MockArticle:
    """Mimics SQLAlchemy Article model with the fields the adapter requires."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.title = kwargs.get("title", "Test")
        self.url = kwargs.get("url", "http://t.com")
        self.source_id = kwargs.get("source_id", "src")
        self.source_name = kwargs.get("source_name", "Source")
        self.summary = kwargs.get("summary", "Summary")
        self.content = kwargs.get("content", "Content")
        self.published_date = kwargs.get("published_date")
        self.collected_date = kwargs.get("collected_date")
        self.final_score = kwargs.get("final_score", 0.5)
        self.article_metadata = kwargs.get("article_metadata", {})
        self.authors = kwargs.get("authors", [])
        self.category = kwargs.get("category", "gen")

    def to_dict(self):
        return self.__dict__.copy()


@pytest.fixture
def coordinator():
    db = MagicMock()
    validator = MagicMock()
    logger = MagicMock()
    logger.create_module_logger.return_value = logger
    return ValidationCoordinator(db_manager=db, validator=validator, logger=logger)


class TestDryRun:
    def test_dry_run_returns_zeros(self, coordinator):
        result = coordinator.execute({}, dry_run=True)
        assert result["success"] is True
        assert result["validated_count"] == 0
        assert result["rejected_count"] == 0


class TestEmptyDatabase:
    def test_no_pending_articles(self, coordinator):
        coordinator.db_manager.get_pending_articles.return_value = []
        result = coordinator.execute({}, dry_run=False)
        assert result["success"] is True
        assert result["validated_count"] == 0
        assert result["rejected_count"] == 0
        coordinator.validator.validate_batch.assert_not_called()


class TestSingleBatch:
    def test_all_valid(self, coordinator):
        articles = [
            _MockArticle(id=1, title="A"),
            _MockArticle(id=2, title="B"),
        ]
        coordinator.db_manager.get_pending_articles.side_effect = [articles, []]
        coordinator.validator.validate_batch.return_value = {
            "invalid": [],
            "valid": [{"id": 1}, {"id": 2}],
        }

        result = coordinator.execute({}, dry_run=False)

        assert result["validated_count"] == 2
        assert result["rejected_count"] == 0
        coordinator.db_manager.update_validation_status_bulk.assert_called_once()
        mappings = coordinator.db_manager.update_validation_status_bulk.call_args[0][0]
        assert len(mappings) == 2
        assert all(m["processing_status"] == "validated" for m in mappings)

    def test_all_invalid(self, coordinator):
        articles = [
            _MockArticle(id=1, title="Bad"),
        ]
        coordinator.db_manager.get_pending_articles.side_effect = [articles, []]
        coordinator.validator.validate_batch.return_value = {
            "invalid": [
                {
                    "article": {"id": 1, "title": "Bad"},
                    "reason": "Too short",
                    "rule": "MinContentLength",
                }
            ],
            "valid": [],
        }

        result = coordinator.execute({}, dry_run=False)

        assert result["validated_count"] == 1
        assert result["rejected_count"] == 1
        coordinator.db_manager.update_validation_status_bulk.assert_called_once()
        mappings = coordinator.db_manager.update_validation_status_bulk.call_args[0][0]
        assert mappings[0]["processing_status"] == "rejected"
        assert "Too short" in mappings[0]["error_message"]

    def test_mixed_valid_invalid(self, coordinator):
        articles = [
            _MockArticle(id=1, title="Valid"),
            _MockArticle(id=2, title="Bad"),
        ]
        coordinator.db_manager.get_pending_articles.side_effect = [articles, []]
        coordinator.validator.validate_batch.return_value = {
            "invalid": [
                {
                    "article": {"id": 2, "title": "Bad"},
                    "reason": "Spam",
                    "rule": "BlocklistPattern",
                }
            ],
            "valid": [{"id": 1}],
        }

        result = coordinator.execute({}, dry_run=False)

        assert result["validated_count"] == 2
        assert result["rejected_count"] == 1

    def test_valid_items_without_id_are_skipped(self, coordinator):
        articles = [_MockArticle(id=1, title="A")]
        coordinator.db_manager.get_pending_articles.side_effect = [articles, []]
        coordinator.validator.validate_batch.return_value = {
            "invalid": [],
            "valid": [{"not_an_id": 1}],  # no 'id' key
        }

        coordinator.execute({}, dry_run=False)

        # No mappings expected — no invalid articles, and valid ones lack an id
        coordinator.db_manager.update_validation_status_bulk.assert_not_called()


class TestMultipleBatches:
    def test_two_batches(self, coordinator):
        # First call returns articles, second returns empty to stop loop
        articles_batch1 = [
            _MockArticle(id=i, title=f"A{i}") for i in range(3)
        ]
        coordinator.db_manager.get_pending_articles.side_effect = [
            articles_batch1,
            [],
        ]
        coordinator.validator.validate_batch.return_value = {
            "invalid": [],
            "valid": [{"id": a.id} for a in articles_batch1],
        }

        result = coordinator.execute({}, dry_run=False)

        assert result["validated_count"] == 3
        assert result["rejected_count"] == 0

    def test_max_batches_halt(self, coordinator, monkeypatch):
        """Infinite-loop guard: MAX_BATCHES reached, halts with error log."""
        monkeypatch.setattr(coordinator, "MAX_BATCHES", 100)
        articles = [_MockArticle(id=1, title="A")]
        # Keep returning articles so loop never naturally ends
        coordinator.db_manager.get_pending_articles.return_value = articles
        coordinator.validator.validate_batch.return_value = {
            "invalid": [],
            "valid": [{"id": 1}],
        }

        result = coordinator.execute({}, dry_run=False)

        assert result["success"] is True  # doesn't crash, just halts
        assert result["validated_count"] == 100  # 100 batches * 1 article
        # Should log the max-batches warning
        coordinator.logger.error.assert_called()


class TestLoggerInteraction:
    def test_validation_completed_event_logged(self, coordinator):
        coordinator.db_manager.get_pending_articles.return_value = []
        coordinator.execute({}, dry_run=False)
        coordinator.logger.info.assert_called_once()
        event_arg = coordinator.logger.info.call_args[0][0]
        assert event_arg["event"] == "validation.completed"
