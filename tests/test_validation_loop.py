import os
import sys
from unittest.mock import MagicMock, patch

# Ensure path is set (might be redundant in some envs)
sys.path.append(os.getcwd())

from news_collector.system import NewsCollectorSystem


class MockArticle:
    def __init__(self, id):
        self.id = id
        self.processing_status = "pending"

    def model_dump(self):
        return {"id": self.id, "title": "Test Article"}


def test_validation_loop_terminates_and_updates_status():
    system = NewsCollectorSystem()
    system.db_manager = MagicMock()
    system.validator = MagicMock()
    # Mock logger factory returns a logger that has methods
    mock_logger = MagicMock()
    system.logger = MagicMock()
    system.logger.create_module_logger.return_value = mock_logger

    # Create a persistent article object
    article1 = MockArticle(1)
    pending_store = [article1]

    def get_pending_side_effect(limit=None, status="pending"):
        # Only return if status matches the article's current status
        return [a for a in pending_store if a.processing_status == status]

    system.db_manager.get_pending_articles.side_effect = get_pending_side_effect

    # Mock DB Session
    session_mock = MagicMock()
    system.db_manager.get_session.return_value.__enter__.return_value = session_mock

    # When session.query(Article).filter_by(id=1).first() is called, return our object
    session_mock.query.return_value.filter_by.return_value.first.return_value = article1

    # Validator returns valid result
    system.validator.validate_batch.return_value = {"valid": [{"id": 1}], "invalid": []}

    # Setup contracts adapter patch because _execute_validation imports it
    with patch(
        "news_collector.contracts.adapters.adapt_to_validation_payload"
    ) as mock_adapt:
        mock_payload = MagicMock()
        mock_payload.articles = [article1]
        mock_adapt.return_value = mock_payload

        # Execute
        system._execute_validation(collection_results={}, dry_run=False)

    # Assertions
    # 1. Status should be updated to 'validated'
    assert (
        article1.processing_status == "validated"
    ), "Status was not updated to validated"

    # 2. Loop should have terminated (called get_pending twice: once got item, second time got empty)
    # Actually validation loop checks 'if not pending_articles: break'.
    # So:
    # Iter 1: get_pending -> [art1]. Validate. Update art1 status to validated.
    # Iter 2: get_pending -> []. Break.
    assert system.db_manager.get_pending_articles.call_count == 2
