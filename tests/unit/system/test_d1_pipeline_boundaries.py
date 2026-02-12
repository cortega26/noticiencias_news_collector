"""
Tests for System Pipeline Boundaries (D1 Phase 2).
Ensures that system boundaries construct payloads using Contracts/Adapters.
"""

from unittest.mock import MagicMock

import pytest
from news_collector.system import NewsCollectorSystem


@pytest.fixture
def mock_system():
    sys = NewsCollectorSystem()
    sys.is_initialized = True
    sys.logger = MagicMock()
    sys.db_manager = MagicMock()
    sys.validator = MagicMock()
    sys.scorer = MagicMock()
    return sys


class MockORMArticle:
    """Mimics SQL Alchemy Article model with typed fields."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.title = kwargs.get("title", "Test")
        self.url = kwargs.get("url", "http://t.com")
        self.source_id = kwargs.get("source_id", "src")
        # Ensure source_name is present for export adapter
        self.source_name = kwargs.get("source_name", "Source")
        self.summary = kwargs.get("summary", "Summary")
        self.content = kwargs.get("content", "Content")
        self.published_date = kwargs.get("published_date")
        self.published_at = kwargs.get("published_at")
        self.collected_date = kwargs.get("collected_date")
        self.final_score = kwargs.get("final_score", 0.5)
        self.article_metadata = kwargs.get("article_metadata", {})
        self.authors = kwargs.get("authors", [])
        self.score_components = kwargs.get("score_components", {})
        self.category = kwargs.get("category", "gen")
        self.published_url = kwargs.get("published_url")
        self.duplication_confidence = kwargs.get("duplication_confidence", 0.1)
        self.word_count = kwargs.get("word_count", 100)
        self.peer_reviewed = False
        self.is_preprint = False
        self.doi = None
        self.journal = None

    def to_dict(self):
        return self.__dict__.copy()


def test_export_boundary_uses_contract(mock_system):
    """Verify export_latest_articles uses ExportContractV2."""
    # Mock DB return
    mock_art = MockORMArticle(id=1, title="Test Export", source_name="Export Src")
    mock_system.db_manager.get_articles_by_score.return_value = [mock_art]

    # Run export
    result = mock_system.export_latest_articles(limit=1)

    # Result should be a dict (serialized model)
    assert isinstance(result, dict)
    assert result["contract"] == "news_collector.export.v2"
    assert result["article_count"] == 1
    assert result["version"] == "2.0"


def test_validation_boundary_uses_payload(mock_system):
    """Verify _execute_validation uses ArticleValidationPayload."""
    # Reset mock to ensure we catch the call
    mock_system.validator.validate_batch = MagicMock(return_value={"invalid": []})

    # Mock DB pending
    mock_art = MockORMArticle(id=2, title="Test Val")
    mock_system.db_manager.get_pending_articles.return_value = [mock_art]

    # Execute
    mock_system._execute_validation({}, dry_run=False)

    # Check validator call args
    args, _ = mock_system.validator.validate_batch.call_args
    passed_list = args[0]
    # It passes a list of dicts (dumped models)
    assert isinstance(passed_list, list)
    assert passed_list[0]["title"] == "Test Val"


@pytest.mark.asyncio
async def test_scoring_boundary_uses_input_model(mock_system):
    """Verify _execute_scoring uses ScoringInputModel."""
    # Mock DB
    mock_art = MockORMArticle(id=10, title="Test Scoring", source_id="src1")
    mock_system.db_manager.get_pending_articles.return_value = [mock_art]

    # Mock Config
    from news_collector.config import ALL_SOURCES

    ALL_SOURCES["src1"] = {}

    # Mock Scorer
    async def fake_score(*args):
        return []

    mock_system.scorer.score_batch_async = fake_score

    # Execute
    await mock_system._execute_scoring({}, dry_run=False)

    # If it didn't crash (ValidationError), the adapter worked.
