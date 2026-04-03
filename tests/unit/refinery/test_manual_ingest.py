from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article


@pytest.fixture(autouse=True)
def _disable_ssrf_guard_for_unit_tests(monkeypatch):
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.validate_url_safety",
        lambda _url: None,
    )


def _saved_article_from_model(article_id: int, model) -> SimpleNamespace:
    payload = model.model_dump_for_storage()
    published_date = payload["published_date"]
    return SimpleNamespace(
        id=article_id,
        title=payload["title"],
        url=payload["url"],
        summary=payload.get("summary"),
        content=payload.get("content"),
        source_name=payload["source_name"],
        source_id=payload["source_id"],
        published_date=published_date,
        published_at=None,
        published_url=None,
        collected_date=published_date,
        article_metadata=payload.get("article_metadata", {}),
        authors=payload.get("authors", []),
        category=payload.get("category"),
        final_score=0.0,
        score_components={},
    )


def _make_existing_article(article_id: int = 10) -> SimpleNamespace:
    published_date = datetime(2026, 3, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=article_id,
        title="Existing article already in database",
        url="https://example.org/manual-article",
        summary="Existing summary already persisted.",
        content="Existing content already persisted for reuse." * 5,
        source_name="Existing Source",
        source_id="existing_source",
        published_date=published_date,
        published_at=None,
        published_url=None,
        collected_date=published_date,
        article_metadata={"image_url": "https://example.org/existing.png"},
        authors=["Existing Author"],
        category="science",
        final_score=0.8,
        score_components={},
    )


def test_resolve_existing_source_by_normalized_host(monkeypatch, tmp_path: Path):
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    sources = {
        "known_source": {
            "name": "Known Source",
            "url": "https://www.example.org/feed.xml",
            "category": "science",
            "enrichment_strategy": "scholarly",
        }
    }

    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        sources,
    )

    source_id, source_cfg, created = service._resolve_or_create_source(
        "https://feeds.example.org/article/123"
    )

    assert source_id == "known_source"
    assert source_cfg["name"] == "Known Source"
    assert created is False
    db.initialize_sources.assert_not_called()


def test_resolve_unmatched_source_creates_and_reuses_manual_source(
    monkeypatch, tmp_path: Path
):
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    sources: dict[str, dict] = {}

    def fake_save_sources(new_sources):
        sources.clear()
        sources.update(new_sources)

    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        sources,
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.save_sources",
        fake_save_sources,
    )

    source_id, source_cfg, created = service._resolve_or_create_source(
        "https://www.custom.example.org/article"
    )
    reused_id, reused_cfg, reused_created = service._resolve_or_create_source(
        "https://feeds.custom.example.org/another-article"
    )

    assert source_id == "manual_custom_example_org"
    assert created is True
    assert source_cfg["manual_only"] is True
    assert source_cfg["update_frequency"] == "manual"
    assert source_cfg["enrichment_strategy"] == "http"
    assert source_cfg["headless_enabled"] is True
    assert sources[source_id]["manual_only"] is True
    db.initialize_sources.assert_called_once_with({source_id: source_cfg})

    assert reused_id == source_id
    assert reused_cfg["name"] == "custom.example.org"
    assert reused_created is False


def test_ingest_reuses_existing_article_without_duplicate_save(tmp_path: Path):
    existing_article = _make_existing_article()
    db = MagicMock()
    db.get_article_by_url.return_value = existing_article
    service = ManualUrlIngestService(db, export_dir=tmp_path)

    result = service.ingest("https://example.org/manual-article?utm_source=test")

    assert result["status"] == "success"
    assert result["article_exists"] is True
    assert result["article_id"] == existing_article.id
    assert result["fetch_attempts"][0]["method"] == "existing_record"
    assert Path(result["export_path"]).exists()
    db.save_article.assert_not_called()


def test_ingest_attempts_all_methods_and_merges_best_payload(
    monkeypatch, tmp_path: Path
):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    saved_models = []

    def fake_save(model):
        saved_models.append(model)
        return _saved_article_from_model(321, model)

    db.save_article.side_effect = fake_save

    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "research_feed": {
                "name": "Research Feed",
                "url": "https://example.org/feed.xml",
                "category": "science",
                "enrichment_strategy": "scholarly",
            }
        },
    )

    service = ManualUrlIngestService(db, export_dir=tmp_path)
    long_content = "Headless recovered full text. " * 60
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {
            "success": True,
            "title": "Crossref Preferred Title",
            "metadata": {
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "created": {"date-parts": [[2024, 2, 20]]},
                "DOI": "10.1000/test-doi",
                "container-title": ["Journal of Tests"],
                "abstract": "<jats:p>Crossref abstract for manual ingestion.</jats:p>",
            },
        }
    )
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": "HTTP text body. " * 20,
            "raw_content": """
                <html>
                  <head>
                    <meta property="og:title" content="HTML Title" />
                    <meta property="og:image" content="/cover.png" />
                    <meta property="article:published_time" content="2024-02-21T12:00:00Z" />
                  </head>
                  <body><p>HTTP paragraph summary.</p></body>
                </html>
            """,
        }
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {
            "success": True,
            "reason": "rendered",
            "content": long_content,
            "raw_content": """
                <html><body><h1>Headless Title</h1><p>Recovered with headless rendering.</p></body></html>
            """,
        }
    )

    result = service.ingest("https://www.example.org/articles/breakthrough?utm_id=123")

    assert result["status"] == "success"
    assert [item["method"] for item in result["fetch_attempts"]] == [
        "scholarly",
        "http",
        "headless",
    ]
    assert saved_models
    saved_model = saved_models[0]
    assert saved_model.source_id == "research_feed"
    assert saved_model.title == "Crossref Preferred Title"
    assert saved_model.content == long_content.strip()
    assert saved_model.summary == "Crossref abstract for manual ingestion."
    assert saved_model.content_mode == "full_text"
    assert saved_model.authors == ["Ada Lovelace"]
    assert saved_model.doi == "10.1000/test-doi"
    assert saved_model.journal == "Journal of Tests"
    assert saved_model.article_metadata.image_url == "https://example.org/cover.png"
    assert saved_model.article_metadata.source_metadata["manual_ingest"][
        "resolved_source_id"
    ] == "research_feed"


def test_ingest_rejects_sparse_manual_source_with_error_code(
    monkeypatch, tmp_path: Path
):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "ars_test": {
                "name": "Ars Technica",
                "url": "https://arstechnica.com/feed/",
                "category": "technology",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(db, export_dir=tmp_path)
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": "Too short to be a trustworthy article export.",
            "raw_content": """
                <html>
                  <head><meta property="og:title" content="Sparse extraction" /></head>
                  <body><p>Too short to be a trustworthy article export.</p></body>
                </html>
            """,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )

    result = service.ingest("https://arstechnica.com/ai/2026/03/sparse-manual-url/")

    assert result["status"] == "error"
    assert result["error_code"] == "source_unusable"
    assert "suficiente texto narrativo" in result["message"]
    db.save_article.assert_not_called()


def test_ingest_rejects_bundle_noise_payload(monkeypatch, tmp_path: Path):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "ars_test": {
                "name": "Ars Technica",
                "url": "https://arstechnica.com/feed/",
                "category": "technology",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(db, export_dir=tmp_path)
    noisy_content = (
        "sourcesContent webpack:// __webpack_require__ function() { const map = []; "
        "export default function leak(){ return map; } let sourceMappingURL = 'app.js.map'; "
    ) * 8
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": noisy_content,
            "raw_content": """
                <html>
                  <head><meta property="og:title" content="Bundle noise" /></head>
                  <body><p>Bundle noise</p></body>
                </html>
            """,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )

    result = service.ingest("https://arstechnica.com/ai/2026/03/bundle-noise/")

    assert result["status"] == "error"
    assert result["error_code"] == "source_unusable"
    assert "ruido técnico o código fuente" in result["message"]
    db.save_article.assert_not_called()


def test_ingest_saves_summary_only_when_full_text_is_unavailable(
    monkeypatch, tmp_path: Path
):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    saved_models = []

    def fake_save(model):
        saved_models.append(model)
        return _saved_article_from_model(401, model)

    db.save_article.side_effect = fake_save
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "summary_feed": {
                "name": "Summary Feed",
                "url": "https://summary.example.net/feed.xml",
                "category": "science",
                "enrichment_strategy": "scholarly",
            }
        },
    )

    service = ManualUrlIngestService(db, export_dir=tmp_path)
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {
            "success": True,
            "title": "Summary Only Article",
            "metadata": {
                "author": [{"given": "Grace", "family": "Hopper"}],
                "created": {"date-parts": [[2025, 1, 5]]},
                "abstract": (
                    "<jats:p>This abstract is all we have, but it still provides enough "
                    "narrative detail to describe the study question, the researchers, "
                    "the methodology, the main finding, the limitations, and the broader "
                    "scientific context. It explains what the team measured, how the "
                    "comparison was designed, which instruments were used, why the result "
                    "matters for the field, and where uncertainty remains. In other words, "
                    "the abstract is long and descriptive enough for a guarded summary-only "
                    "manual ingestion flow to remain trustworthy without turning into a "
                    "placeholder article.</jats:p>"
                ),
            },
        }
    )
    service.http = SimpleNamespace(
        enrich=lambda _url: {"success": False, "reason": "blocked"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "timeout"}
    )

    result = service.ingest("https://summary.example.net/article")

    assert result["status"] == "success"
    assert saved_models[0].content is None
    assert saved_models[0].summary.startswith("This abstract is all we have")
    assert saved_models[0].content_mode == "summary_only"


def test_ingest_fails_without_persistence_when_no_valid_payload_exists(
    monkeypatch, tmp_path: Path
):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "blocked_source": {
                "name": "Blocked Source",
                "url": "https://blocked.example.com/feed.xml",
                "category": "science",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(db, export_dir=tmp_path)
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_found"}
    )
    service.http = SimpleNamespace(
        enrich=lambda _url: {"success": False, "reason": "blocked"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "timeout"}
    )

    result = service.ingest("https://blocked.example.com/article")

    assert result["status"] == "error"
    assert result["error_code"] == "source_unusable"
    assert result["source_id"] == "blocked_source"
    assert [item["method"] for item in result["fetch_attempts"]] == [
        "http",
        "scholarly",
        "headless",
    ]
    db.save_article.assert_not_called()


@pytest.fixture
def sqlite_db(tmp_path: Path):
    db = DatabaseManager(
        database_config={"type": "sqlite", "path": tmp_path / "manual_ingest.db"}
    )
    try:
        yield db
    finally:
        db.close()


def test_ingest_real_db_new_article_detached_export_path_is_stable(
    monkeypatch, tmp_path: Path, sqlite_db: DatabaseManager
):
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "ars_test": {
                "name": "Ars Technica",
                "url": "https://arstechnica.com/feed/",
                "category": "technology",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(sqlite_db, export_dir=tmp_path / "exports")
    article_url = (
        "https://arstechnica.com/ai/2026/03/"
        "entire-claude-code-cli-source-code-leaks-thanks-to-exposed-map-file/"
    )
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": "Ars article body extracted for regression hardening. " * 40,
            "raw_content": """
                <html>
                  <head>
                    <meta property="og:title" content="Entire Claude Code CLI source code leaks thanks to exposed map file" />
                    <meta property="og:description" content="Regression summary for detached export safety." />
                    <meta property="og:image" content="https://cdn.arstechnica.net/test-image.png" />
                    <meta property="article:published_time" content="2026-03-31T12:00:00Z" />
                  </head>
                  <body><p>Detached export regression body.</p></body>
                </html>
            """,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )

    result = service.ingest(article_url)

    assert result["status"] == "success"
    assert result["article_exists"] is False
    assert result["published"] is False
    assert result["published_candidate"] is False
    assert result["publish_ready"] is False
    assert result["publication_state"] == "UNPUBLISHED"
    assert Path(result["export_path"]).exists()
    assert result["article"]["title"].startswith("Entire Claude Code CLI")
    assert result["article"]["published_at"] is None
    assert result["article"]["published_url"] is None


def test_ingest_real_db_existing_article_reuses_record_without_duplicates(
    monkeypatch, tmp_path: Path, sqlite_db: DatabaseManager
):
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "ars_test": {
                "name": "Ars Technica",
                "url": "https://arstechnica.com/feed/",
                "category": "technology",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(sqlite_db, export_dir=tmp_path / "exports")
    article_url = "https://arstechnica.com/ai/2026/03/duplicate-regression/"
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": "Duplicate regression article body. " * 35,
            "raw_content": """
                <html>
                  <head>
                    <meta property="og:title" content="Duplicate regression article title for manual ingest" />
                    <meta property="og:description" content="Duplicate regression summary." />
                    <meta property="article:published_time" content="2026-03-30T08:00:00Z" />
                  </head>
                  <body><p>Duplicate regression body.</p></body>
                </html>
            """,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )

    first_result = service.ingest(article_url)
    second_result = service.ingest(article_url)

    assert first_result["status"] == "success"
    assert second_result["status"] == "success"
    assert second_result["article_exists"] is True
    assert second_result["article_id"] == first_result["article_id"]
    assert Path(second_result["export_path"]).exists()
    assert second_result["fetch_attempts"][0]["method"] == "existing_record"

    with sqlite_db.get_session() as session:
        article_count = session.query(Article).count()

    assert article_count == 1


def test_ingest_result_can_be_consumed_by_streamlit_url_loader(
    monkeypatch, tmp_path: Path, sqlite_db: DatabaseManager
):
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "ars_test": {
                "name": "Ars Technica",
                "url": "https://arstechnica.com/feed/",
                "category": "technology",
                "enrichment_strategy": "http",
            }
        },
    )

    service = ManualUrlIngestService(sqlite_db, export_dir=tmp_path / "exports")
    article_url = (
        "https://arstechnica.com/ai/2026/03/"
        "entire-claude-code-cli-source-code-leaks-thanks-to-exposed-map-file/"
    )
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": "Streamlit loader regression body. " * 35,
            "raw_content": """
                <html>
                  <head>
                    <meta property="og:title" content="Manual URL loader regression for Streamlit" />
                    <meta property="og:description" content="Streamlit loader should be able to consume this result." />
                    <meta property="article:published_time" content="2026-03-29T09:00:00Z" />
                  </head>
                  <body><p>Streamlit loader regression body.</p></body>
                </html>
            """,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )

    result = service.ingest(article_url)
    session_state = {}
    session_state["manual_loaded_article"] = result.get("article")
    session_state["manual_loaded_export_path"] = result.get("export_path")
    session_state["manual_loaded_fetch_attempts"] = result.get("fetch_attempts", [])
    session_state["manual_loaded_source_id"] = result.get("source_id")
    session_state["manual_loaded_source_created"] = result.get(
        "source_created", False
    )
    session_state["manual_loaded_article_exists"] = result.get("article_exists", False)

    assert result["status"] == "success"
    assert session_state["manual_loaded_article"]["id"] == result["article_id"]
    assert session_state["manual_loaded_export_path"] == result["export_path"]
    assert isinstance(session_state["manual_loaded_fetch_attempts"], list)
