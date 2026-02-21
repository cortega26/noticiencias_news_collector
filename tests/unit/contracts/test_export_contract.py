"""Tests for Export Contract V1."""

from datetime import datetime, timezone

from news_collector.contracts.export import ExportArticleModel, ExportContractV2


def test_export_contract_v2_valid():
    """Verify standard export payload construction."""
    article = ExportArticleModel(
        id=1,
        title="Valid Export",
        url="http://test.com",
        source_name="Test",
        source_id="test_id",
        score=0.9,
    )

    contract = ExportContractV2(
        generated_at=datetime.now(timezone.utc).isoformat(),
        article_count=1,
        articles=[article],
    )

    dump = contract.model_dump()
    assert dump["contract"] == "news_collector.export.v2"
    assert dump["schema_version"] == 2
    assert dump["version"] == "2.0"
    assert dump["article_count"] == 1
    assert dump["articles"][0]["title"] == "Valid Export"


def test_export_contract_defaults():
    """Verify default values in export contract."""
    article = ExportArticleModel(
        id=1,
        title="Defaults",
        url="http://def.com",
        source_name="Source",
        source_id="def_id",
    )
    contract = ExportContractV2(
        generated_at="2025-01-01T00:00:00Z", article_count=1, articles=[article]
    )
    assert contract.articles[0].metadata == {}
    assert contract.articles[0].components == {}
