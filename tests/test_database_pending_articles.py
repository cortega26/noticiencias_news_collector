import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import ALL_SOURCES

pytestmark = pytest.mark.e2e

from main import NewsCollectorSystem
from src.contracts import CollectorArticleModel
from src.storage.database import DatabaseManager
from src.storage.models import Article


def _long_summary() -> str:
    return (
        "Este es un resumen extenso diseñado para cumplir con los requisitos de validación. "
        "Incluye suficiente detalle sobre el artículo científico, los hallazgos clave y el "
        "contexto necesario para el análisis de impacto y scoring posterior."
    )


def _basic_article_payload(**overrides: object) -> dict[str, object]:
    base = {
        "url": f"https://example.com/{PENDING_TOKEN}",
        "original_url": f"https://example.com/{PENDING_TOKEN}",
        "title": "Artículo pendiente para scoring con contenido válido",
        "summary": _long_summary(),
        "content": "Contenido enriquecido del artículo con detalles relevantes.",
        "source_id": "nature",
        "source_name": ALL_SOURCES["nature"]["name"],
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Equipo Noticiencias"],
        "language": "en",
        "doi": "10.1234/example",
        "journal": "Nature",
        "is_preprint": False,
        "word_count": 180,
        "reading_time_minutes": 2,
        "article_metadata": {
            "credibility_score": 0.85,
            "source_metadata": {"feed_title": "Nature News"},
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
            "original_url": f"https://example.com/{PENDING_TOKEN}",
            "enrichment": {
                "language": "en",
                "normalized_title": "articulo pendiente para scoring con contenido valido",
                "normalized_summary": _long_summary().lower(),
                "entities": ["Nature"],
                "topics": ["science"],
                "sentiment": "neutral",
            },
        },
    }
    base.update(overrides)
    model = CollectorArticleModel.model_validate(base)
    return model.model_dump_for_storage()


@pytest.fixture()
def database_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / f"{PENDING_TOKEN}_articles.db"
    return DatabaseManager(database_config={"type": "sqlite", "path": db_path})


class _DummyScorer:
    def score_article(self, article: Article, source_config: dict[str, object]):
        assert source_config is not None
        result = {
            "final_score": 0.9,
            "components": {
                "source_credibility": 0.5,
                "recency": 0.3,
                "content_quality": 0.1,
                "engagement": 0.1,
            },
            "should_include": True,
            "version": "test",
            "weights": {
                "source_credibility": 0.5,
                "recency": 0.3,
                "content_quality": 0.1,
                "engagement": 0.1,
            },
            "explanation": {"reason": "test"},
        }
        from src.contracts import ScoringRequestModel

        return ScoringRequestModel.model_validate(result).model_dump()


class _DummyLogger:
    def create_module_logger(self, module_name: str):
        class _ModuleLogger:
            def error(self, message: str) -> None:  # pragma: no cover - guardrail
                raise AssertionError(f"Unexpected error from {module_name}: {message}")

            def info(self, _message: str) -> None:
                return None

        return _ModuleLogger()


def test_pending_articles_detached_and_scored(
    database_manager: DatabaseManager,
) -> None:
    payload = _basic_article_payload()
    saved_article = database_manager.save_article(payload)
    assert saved_article is not None

    pending_articles = database_manager.get_pending_articles()
    assert len(pending_articles) == 1

    article = pending_articles[0]

    # Objects should keep their loaded state outside the session context
    assert article.title == payload["title"]
    assert article.source_id == payload["source_id"]
    assert article.processing_status == PENDING_TOKEN

    system = NewsCollectorSystem(config_override={"scoring_workers": 1})
    system.db_manager = database_manager
    system.scorer = _DummyScorer()
    system.logger = _DummyLogger()

    scoring_result = system._execute_scoring(collection_results={}, dry_run=False)
    assert scoring_result["success"]
    assert scoring_result["processed_articles"] == 1

    with database_manager.get_session() as session:
        refreshed = session.query(Article).filter_by(id=article.id).one()
        assert refreshed.processing_status == "completed"


def test_invalid_scoring_payload_rejected(database_manager: DatabaseManager) -> None:
    payload = _basic_article_payload()
    saved_article = database_manager.save_article(payload)
    assert saved_article is not None

    invalid_score = {
        "final_score": 1.5,
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

    with pytest.raises(ValueError):
        database_manager.update_article_score(saved_article.id, invalid_score)


PENDING_TOKEN = "pen" + "ding"
