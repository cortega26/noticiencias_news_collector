from __future__ import annotations

import sys
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
from src.storage.database import DatabaseManager
from src.storage.models import Article


@pytest.fixture()
def database_manager(tmp_path: Path) -> DatabaseManager:
    db_path = tmp_path / "pending_articles.db"
    return DatabaseManager(database_config={"type": "sqlite", "path": db_path})


def _basic_article_payload() -> dict[str, object]:
    return {
        "url": "https://example.com/pending",
        "title": "Artículo pendiente para scoring",
        "summary": "Resumen breve del artículo pendiente.",
        "content": "Contenido del artículo pendiente.",
        "source_id": "nature",
        "source_name": ALL_SOURCES["nature"]["name"],
        "category": "science",
    }


class _DummyScorer:
    def score_article(self, article: Article, source_config: dict[str, object]):
        assert source_config is not None
        return {
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


class _DummyLogger:
    def create_module_logger(self, module_name: str):
        class _ModuleLogger:
            def error(self, message: str) -> None:  # pragma: no cover - guardrail
                raise AssertionError(f"Unexpected error from {module_name}: {message}")

            def info(self, _message: str) -> None:
                return None

        return _ModuleLogger()


def test_pending_articles_detached_and_scored(database_manager: DatabaseManager) -> None:
    payload = _basic_article_payload()
    saved_article = database_manager.save_article(payload)
    assert saved_article is not None

    pending_articles = database_manager.get_pending_articles()
    assert len(pending_articles) == 1

    article = pending_articles[0]

    # Objects should keep their loaded state outside the session context
    assert article.title == payload["title"]
    assert article.source_id == payload["source_id"]
    assert article.processing_status == "pending"

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

