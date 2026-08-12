from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article, ScoreLog

pytestmark = pytest.mark.e2e


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "api.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_path})
    with manager.get_session() as session:
        base_time = datetime.now(timezone.utc)
        articles: List[Dict] = [
            {
                "title": "CRISPR gene therapy milestone",
                "url": "https://example.com/crispr",
                "summary": "Breakthrough in CRISPR gene therapy",
                "source_id": "nature",
                "source_name": "Nature",
                "category": "science",
                "final_score": 0.92,
                "published_date": base_time - timedelta(hours=6),
                "collected_date": base_time - timedelta(hours=4),
                "topics": ["science", "health"],
                "components": {
                    "source_credibility": 0.95,
                    "recency": 0.85,
                    "content_quality": 0.9,
                    "engagement_potential": 0.88,
                },
                "strengths": [
                    "Fuente altamente confiable",
                    "Publicado hace pocas horas",
                    "Contenido con alta calidad científica",
                ],
            },
            {
                "title": "Space telescope survey",
                "url": "https://example.com/space",
                "summary": "New survey maps distant galaxies",
                "source_id": "esa",
                "source_name": "ESA",
                "category": "science",
                "final_score": 0.75,
                "published_date": base_time - timedelta(days=1),
                "collected_date": base_time - timedelta(hours=20),
                "topics": ["science", "space"],
                "components": {
                    "source_credibility": 0.8,
                    "recency": 0.6,
                    "content_quality": 0.7,
                    "engagement_potential": 0.7,
                },
                "strengths": [
                    "Cobertura exclusiva de misión espacial",
                ],
            },
            {
                "title": "Metabolic health study",
                "url": "https://example.com/health",
                "summary": "Clinical trial shows metabolic impact",
                "source_id": "nejm",
                "source_name": "NEJM",
                "category": "health",
                "final_score": 0.82,
                "published_date": base_time - timedelta(days=2),
                "collected_date": base_time - timedelta(days=1, hours=10),
                "topics": ["health"],
                "components": {
                    "source_credibility": 0.92,
                    "recency": 0.55,
                    "content_quality": 0.8,
                    "engagement_potential": 0.76,
                },
                "strengths": [
                    "Estudio clínico revisado por pares",
                    "Relevancia directa para salud pública",
                ],
            },
        ]

        for payload in articles:
            article = Article(
                title=payload["title"],
                url=payload["url"],
                summary=payload["summary"],
                source_id=payload["source_id"],
                source_name=payload["source_name"],
                category=payload["category"],
                final_score=payload["final_score"],
                published_date=payload["published_date"],
                collected_date=payload["collected_date"],
                processing_status="completed",
                cluster_id="cluster-story",
                article_metadata={
                    "enrichment": {"topics": payload["topics"]},
                },
                score_components=payload["components"],
            )
            session.add(article)
            session.flush()
            session.add(
                ScoreLog(
                    article_id=article.id,
                    score_version="1.0",
                    final_score=payload["final_score"],
                    score_explanation={
                        "key_strengths": payload["strengths"],
                        "component_breakdown": {},
                    },
                    algorithm_weights={
                        "source_credibility": 0.25,
                        "recency": 0.25,
                        "content_quality": 0.25,
                        "engagement_potential": 0.25,
                    },
                )
            )
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture()
def api_client(db_manager: DatabaseManager) -> TestClient:
    app = create_app(database_manager=db_manager)
    return TestClient(app)


def test_articles_filtering_and_why_ranked(api_client: TestClient):
    params = {
        "source": "nature",
        "topic": "health",
        "date_from": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }
    response = api_client.get("/v1/articles", params=params)
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["returned"] == 1
    article = payload["data"][0]
    assert article["source"]["id"] == "nature"
    assert "Fuente altamente confiable" in article["why_ranked"]
    assert "health" in article["topics"]


def test_articles_pagination_is_stable(api_client: TestClient):
    first_page = api_client.get("/v1/articles", params={"page_size": 2})
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["pagination"]["returned"] == 2
    cursor = first_payload["pagination"]["next_cursor"]
    assert cursor

    second_page = api_client.get(
        "/v1/articles", params={"cursor": cursor, "page_size": 2}
    )
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert second_payload["pagination"]["returned"] == 1

    full_payload = api_client.get("/v1/articles", params={"page_size": 10}).json()
    full_ids = [item["id"] for item in full_payload["data"]]
    assert [item["id"] for item in first_payload["data"]] == full_ids[:2]
    assert [item["id"] for item in second_payload["data"]] == full_ids[2:3]


def test_health_and_readiness(api_client: TestClient):
    health = api_client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] in {"ok", "degraded"}

    ready = api_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_related_articles_returns_empty_list_without_cluster(
    api_client: TestClient, db_manager: DatabaseManager
):
    with db_manager.get_session() as session:
        standalone = Article(
            title="Standalone report",
            url="https://example.com/standalone",
            source_id="solo",
            source_name="Solo Source",
            processing_status="completed",
            cluster_id=None,
        )
        session.add(standalone)
        session.flush()
        article_id = standalone.id

    response = api_client.get(f"/v1/articles/{article_id}/related")

    assert response.status_code == 200
    assert response.json() == []


def test_related_articles_returns_siblings_in_deterministic_order(
    api_client: TestClient,
):
    response = api_client.get("/v1/articles/2/related")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [1, 3]
    assert payload[0]["source"] == {"id": "nature", "name": "Nature"}
    assert [item["score"] for item in payload] == [0.92, 0.82]


def test_related_articles_returns_not_found_for_unknown_id(api_client: TestClient):
    response = api_client.get("/v1/articles/999/related")

    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


# ---------------------------------------------------------------------------
# Cursor/pagination edge-case tests (Plan 045 Step 1)
# ---------------------------------------------------------------------------


def test_cursor_traversal_completes_without_gaps_or_duplicates(api_client: TestClient):
    """Every article appears exactly once across all pages."""
    page_size = 2
    seen: set[int] = set()
    cursor = None

    while True:
        params = {"page_size": page_size}
        if cursor:
            params["cursor"] = cursor
        resp = api_client.get("/v1/articles", params=params)
        assert resp.status_code == 200
        body = resp.json()
        for item in body["data"]:
            item_id = item["id"]
            assert item_id not in seen, f"Duplicate article {item_id}"
            seen.add(item_id)
        cursor = body["pagination"].get("next_cursor")
        if not cursor or body["pagination"]["returned"] < page_size:
            break

    assert len(seen) == 3, f"Expected 3 unique articles, got {len(seen)}"


def test_malformed_cursor_returns_400(api_client: TestClient):
    """A base64-decodable-but-invalid cursor must return 400."""
    resp = api_client.get("/v1/articles", params={"cursor": "not-valid-base64!!!"})
    assert resp.status_code == 400


def test_ranked_articles_include_final_score(api_client: TestClient):
    """All ranked articles include the final_score field."""
    resp = api_client.get("/v1/articles")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) > 0
    for item in data:
        assert "final_score" in item
        assert isinstance(item["final_score"], (int, float, type(None)))


def test_date_filter_boundaries_are_inclusive(api_client: TestClient, db_manager):
    """date_from and date_to include articles on the boundary."""
    with db_manager.get_session() as session:
        article = session.query(Article).filter(Article.source_id == "nature").first()
        assert article and article.published_date

    date_iso = article.published_date.isoformat()
    resp = api_client.get(
        "/v1/articles", params={"date_from": date_iso, "date_to": date_iso}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    ids = [item["id"] for item in data]
    assert article.id in ids


def test_empty_result_set_returns_valid_envelope(api_client: TestClient):
    """A date range with no matches returns valid empty envelope."""
    far_future = "2099-01-01T00:00:00"
    resp = api_client.get(
        "/v1/articles", params={"date_from": far_future, "date_to": far_future}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["returned"] == 0
    assert body["data"] == []
    assert body["pagination"]["next_cursor"] is None
