from datetime import datetime, timezone
from unittest.mock import MagicMock

from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from news_collector.system import NewsCollectorSystem
from news_collector.utils.logger import get_logger

_FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_validation_loop_terminates_and_updates_status(tmp_path):
    """The coordinator must drain the real pending queue and persist the
    terminal transition into real SQLite — no storage doubles.

    Only the validator is doubled: it is the LLM boundary and must not call
    a model. Everything around it (queue, adapter, bulk status update,
    logger) is the production implementation.
    """
    system = NewsCollectorSystem()
    db_manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "loop.db"})
    system.db_manager = db_manager

    with db_manager.get_session() as session:
        article = Article(
            title="Pending article for validation",
            url="https://example.com/validation-loop",
            summary="Pending article summary",
            source_id="test_source",
            source_name="Test Source",
            processing_status="pending",
            published_date=_FIXED_NOW,
            collected_date=_FIXED_NOW,
        )
        session.add(article)
        session.flush()
        article_id = article.id
        assert article_id is not None

    system.validator = MagicMock()
    system.validator.validate_batch.return_value = {
        "valid": [{"id": article_id}],
        "invalid": [],
    }
    system.logger = get_logger()

    try:
        results = system._execute_validation(collection_results={}, dry_run=False)

        assert results["validated_count"] == 1
        with db_manager.get_session() as session:
            persisted = session.query(Article).filter_by(id=article_id).one()
            assert (
                persisted.processing_status == "validated"
            ), "Status was not updated to validated"
    finally:
        db_manager.close()
