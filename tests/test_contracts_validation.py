import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import ALL_SOURCES
from src.contracts import (
    CollectorArticleModel,
    ScoringRequestModel,
)


def _valid_collector_payload() -> dict[str, object]:
    summary = (
        "Resumen suficientemente largo para cumplir las reglas del contrato y validar "
        "que los artículos poseen información adecuada para el pipeline completo."
    )
    return {
        "url": "https://example.com/valid",
        "original_url": "https://example.com/valid",
        "title": "Artículo válido para contratos",
        "summary": summary,
        "content": "Contenido extendido para las pruebas.",
        "source_id": "nature",
        "source_name": ALL_SOURCES["nature"]["name"],
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Equipo"],
        "language": "en",
        "word_count": 150,
        "reading_time_minutes": 2,
        "article_metadata": {
            "credibility_score": 0.8,
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
            "original_url": "https://example.com/valid",
            "enrichment": {
                "language": "en",
                "normalized_title": "articulo valido para contratos",
                "normalized_summary": summary.lower(),
                "entities": ["Example"],
                "topics": ["science"],
                "sentiment": "neutral",
            },
        },
    }


def test_collector_contract_requires_published_date() -> None:
    payload = _valid_collector_payload()
    payload.pop("published_date")

    with pytest.raises(ValidationError):
        CollectorArticleModel.model_validate(payload)


def test_collector_contract_rejects_invalid_url() -> None:
    payload = _valid_collector_payload()
    payload["url"] = "nota-url"

    with pytest.raises(ValidationError):
        CollectorArticleModel.model_validate(payload)


def test_scoring_request_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        ScoringRequestModel.model_validate(
            {
                "final_score": 1.2,
                "should_include": True,
                "components": {
                    "source_credibility": 0.5,
                    "recency": 0.3,
                    "content_quality": 0.1,
                    "engagement": 0.1,
                },
                "weights": {
                    "source_credibility": 0.5,
                    "recency": 0.3,
                    "content_quality": 0.1,
                    "engagement": 0.1,
                },
                "version": "test",
                "explanation": {"reason": "invalid"},
            }
        )
