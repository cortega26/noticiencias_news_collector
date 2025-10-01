import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors import RSSCollector
from src.scoring import create_scorer
from src.storage import models as storage_models
from src.storage.database import DatabaseManager


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "data" / "collector_pipeline_chain.json"
)


@pytest.fixture(scope="module")
def pipeline_dataset() -> List[Dict[str, object]]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def isolated_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> DatabaseManager:
    db_path = tmp_path / "pipeline.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})

    import src.storage.database as database_module

    # Reset singleton for test isolation
    monkeypatch.setattr(database_module, "_db_manager", manager, raising=False)
    monkeypatch.setattr(
        "src.collectors.rss_collector.get_database_manager", lambda: manager
    )

    return manager


def _prepare_raw_article(entry: Dict[str, object]) -> Dict[str, object]:
    collector_raw = dict(entry["collector_raw"])  # shallow copy
    offset_hours = collector_raw.pop("published_offset_hours")
    published_dt = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    collector_raw["published_date"] = published_dt
    collector_raw.setdefault("published_tz_offset_minutes", 0)
    collector_raw.setdefault("published_tz_name", "UTC")
    collector_raw.setdefault("original_url", collector_raw["url"])
    collector_raw.setdefault("source_metadata", {})
    return collector_raw


def test_collector_pipeline_end_to_end(
    isolated_database: DatabaseManager,
    pipeline_dataset: List[Dict[str, object]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = RSSCollector()

    # Mock external IO interactions
    monkeypatch.setattr(RSSCollector, "_respect_robots", lambda self, url: (True, None))
    monkeypatch.setattr(
        RSSCollector,
        "_enforce_domain_rate_limit",
        lambda self, domain, robots_delay, source_min_delay=None: None,
    )
    monkeypatch.setattr(
        RSSCollector, "_fetch_feed", lambda self, source_id, feed_url: ("<rss/>", 200)
    )

    mock_feed = type("MockFeed", (), {"bozo": 0})()
    monkeypatch.setattr("feedparser.parse", lambda content: mock_feed)

    def fake_extract(self, parsed_feed, source_config):
        return getattr(self, "_test_articles", [])

    monkeypatch.setattr(RSSCollector, "_extract_articles_from_feed", fake_extract)

    recon_records: List[Dict[str, object]] = []

    scorer = create_scorer()

    for entry in pipeline_dataset:
        source = entry["source"]
        raw_article = _prepare_raw_article(entry)
        collector._test_articles = [raw_article]

        source_config = {
            "name": source["name"],
            "url": source["url"],
            "category": source["category"],
            "credibility_score": source["credibility_score"],
            "language": source.get("language", "en"),
        }

        stats = collector.collect_from_source(source["id"], source_config)

        assert stats["success"] is True
        assert stats["articles_saved"] == 1

        with isolated_database.get_session() as session:
            stored_article = (
                session.query(storage_models.Article)
                .filter_by(url=raw_article["url"])
                .first()
            )
            assert stored_article is not None, "article should be persisted"
            enrichment = stored_article.article_metadata.get("enrichment", {})

        expected_enrichment = entry["enrichment_expected"]
        assert enrichment.get("language") == expected_enrichment["language"]
        assert enrichment.get("sentiment") == expected_enrichment["sentiment"]
        actual_topics = enrichment.get("topics", [])
        for topic in expected_enrichment["topics"]:
            assert topic in actual_topics
        actual_entities = enrichment.get("entities", [])
        for entity in expected_enrichment["entities"]:
            assert entity in actual_entities

        score_payload = scorer.score_article(stored_article)
        assert (
            score_payload["should_include"]
            == entry["expected_storage"]["should_include"]
        )

        updated = isolated_database.update_article_score(
            stored_article.id, score_payload
        )
        assert updated is True

        with isolated_database.get_session() as session:
            post_article = (
                session.query(storage_models.Article)
                .filter_by(id=stored_article.id)
                .first()
            )
            logs = (
                session.query(storage_models.ScoreLog)
                .filter_by(article_id=stored_article.id)
                .all()
            )

        assert post_article is not None
        assert len(logs) == 1

        expected_fields = entry["expected_storage"]["fields"]
        for field_name, expected_value in expected_fields.items():
            assert getattr(post_article, field_name) == expected_value

        assert post_article.processing_status == "completed"
        assert post_article.final_score is not None
        assert post_article.final_score >= entry["expected_storage"]["final_score_min"]
        assert isinstance(post_article.score_components, dict)

        for component_name in (
            "source_credibility",
            "recency",
            "content_quality",
            "engagement",
        ):
            component_value = post_article.score_components.get(component_name)
            assert component_value is not None
            assert 0.0 <= component_value <= 1.0

        recon_records.append(
            {
                "id": entry["id"],
                "expected": {
                    **entry["expected_storage"],
                    "enrichment": entry["enrichment_expected"],
                },
                "actual": {
                    "language": post_article.language,
                    "category": post_article.category,
                    "source_id": post_article.source_id,
                    "final_score": post_article.final_score,
                    "processing_status": post_article.processing_status,
                    "score_components": post_article.score_components,
                    "should_include": score_payload["should_include"],
                    "enrichment": enrichment,
                },
            }
        )

    with isolated_database.get_session() as session:
        total_logs = session.query(storage_models.ScoreLog).count()
    assert total_logs == len(pipeline_dataset)

    artifact_path = tmp_path / "pipeline_reconciliation.json"
    with artifact_path.open("w", encoding="utf-8") as fh:
        json.dump({"entries": recon_records}, fh, ensure_ascii=False, indent=2)

    # Attach artifact path to help CI collect it
    print(f"pipeline_reconciliation_artifact={artifact_path}")
