"""Branch coverage for manual-ingest helpers and ingest seams (plan 100 gate).

``manual_ingest.py`` is a changed module, so the coverage ratchet requires
>=90% line coverage on it. These tests pin the pure parsing helpers and the
ingest error seams directly (deterministic, no network).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from news_collector.logic.workflows import manual_ingest
from news_collector.logic.workflows.manual_ingest import (
    ManualUrlIngestService,
    _excerpt_from_text,
    _extract_html_metadata,
    _extract_scholarly_metadata,
    _json_ld_items,
    _parse_datetime,
    _split_authors,
)


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def test_parse_datetime_branches():
    assert _parse_datetime(None) is None
    assert _parse_datetime("   ") is None
    assert _parse_datetime("not-a-date") is None
    assert _parse_datetime("2026-03-31T12:00:00Z") == datetime(
        2026, 3, 31, 12, 0, tzinfo=timezone.utc
    )
    assert _parse_datetime("2026-03-31 12:00:00") == datetime(
        2026, 3, 31, 12, 0, tzinfo=timezone.utc
    )


def test_excerpt_branches():
    assert _excerpt_from_text(None) is None
    assert _excerpt_from_text("short") == "short"
    long_text = _words(100)
    excerpt = _excerpt_from_text(long_text)
    assert excerpt is not None and excerpt.endswith("\u2026")
    assert len(excerpt) <= 281


def test_json_ld_items_branches():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<html><head>"
        '<script type="application/ld+json"></script>'
        '<script type="application/ld+json">not json</script>'
        '<script type="application/ld+json">["just", "strings"]</script>'
        '<script type="application/ld+json">'
        + json.dumps(
            [
                {"@type": "NewsArticle", "headline": "Ld Title"},
                {"@type": "WebPage", "name": "Ignored"},
            ]
        )
        + "</script>"
        '<script type="application/ld+json">'
        + json.dumps({"@type": "Article", "headline": "Single"})
        + "</script>"
        "</head></html>",
        "html.parser",
    )
    headlines = [item.get("headline") for item in _json_ld_items(soup)]
    assert headlines == ["Ld Title", None, "Single"]


def test_split_authors_branches():
    assert _split_authors(None) == []
    assert _split_authors("") == []
    assert _split_authors("Ada Lovelace, Grace Hopper and Margaret Hamilton;x") == [
        "Ada Lovelace",
        "Grace Hopper",
        "Margaret Hamilton",
        "x",
    ]


def test_html_metadata_json_ld_merge_list_authors():
    raw_html = (
        "<html><head>"
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "NewsArticle",
                "headline": "Merged LD Title",
                "description": "Merged LD summary.",
                "author": [
                    {"name": "Ada Lovelace"},
                    "Grace Hopper",
                    {"name": None},
                ],
                "image": "https://cdn.example.org/ld.png",
                "datePublished": "2026-04-02T10:00:00Z",
                "identifier": "10.1000/ld-doi",
                "publisher": {"name": "LD Journal"},
            }
        )
        + "</script>"
        "</head><body><div>Body without paragraph fallback.</div></body></html>"
    )
    metadata = _extract_html_metadata(raw_html, "https://probe.example.org/a")

    assert metadata["title"] == "Merged LD Title"
    assert metadata["summary"] == "Merged LD summary."
    assert metadata["authors"] == ["Ada Lovelace", "Grace Hopper"]
    assert metadata["image_url"] == "https://cdn.example.org/ld.png"
    assert metadata["published_date"] == datetime(
        2026, 4, 2, 10, 0, tzinfo=timezone.utc
    )
    assert metadata["doi"] == "10.1000/ld-doi"
    assert metadata["journal"] == "LD Journal"


def test_html_metadata_json_ld_merge_string_author_and_list_type():
    raw_html = (
        "<html><head>"
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": ["BlogPosting", "ScholarlyArticle"],
                "headline": "String Author Title",
                "author": "Solo Researcher",
            }
        )
        + "</script>"
        "</head><body><p>Fallback.</p></body></html>"
    )
    metadata = _extract_html_metadata(raw_html, "https://probe.example.org/a")

    assert metadata["title"] == "String Author Title"
    assert metadata["authors"] == ["Solo Researcher"]


def test_html_metadata_skips_non_article_json_ld():
    raw_html = (
        "<html><head><title>Plain Title</title>"
        '<script type="application/ld+json">'
        + json.dumps({"@type": "WebPage", "name": "Not an article"})
        + "</script>"
        "</head><body><p>Plain body.</p></body></html>"
    )
    metadata = _extract_html_metadata(raw_html, "https://probe.example.org/a")

    assert metadata["title"] == "Plain Title"
    assert metadata["summary"] == "Plain body."
    assert metadata["authors"] == []


def test_scholarly_metadata_bad_date_parts():
    metadata = _extract_scholarly_metadata(
        {
            "title": "Scholarly Probe",
            "metadata": {
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "created": {"date-parts": [["nope"]]},
                "abstract": "<jats:p>Abstract text.</jats:p>",
                "container-title": ["Journal of Probes"],
                "DOI": "10.1000/probe",
            },
        }
    )

    assert metadata["published_date"] is None
    assert metadata["authors"] == ["Ada Lovelace"]
    assert metadata["journal"] == "Journal of Probes"


def test_scholarly_metadata_missing_block():
    assert _extract_scholarly_metadata({"title": "No meta"}) == {}


def test_manual_policy_falls_back_to_schema_defaults(monkeypatch, tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    monkeypatch.setattr(
        manual_ingest,
        "get_runtime_config",
        MagicMock(side_effect=RuntimeError("config unavailable")),
    )

    policy = service._manual_policy()

    assert policy == {
        "manual_ingest_source_credibility": 0.5,
        "manual_ingest_source_tier": "D",
        "manual_ingest_min_words": 80,
        "manual_ingest_summary_min_words": 40,
    }


def test_ingest_rejects_empty_url(tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)

    result = service.ingest("   ")

    assert result["status"] == "error"
    assert "inválida" in result["message"]


def test_ingest_rejects_blocked_url(monkeypatch, tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)

    def _blocked(_url: str) -> None:
        raise ValueError("denied")

    monkeypatch.setattr(manual_ingest, "validate_url_safety", _blocked)

    result = service.ingest("https://probe.example.org/article")

    assert result["status"] == "error"
    assert result["message"] == "URL bloqueada: denied"


def test_ingest_rejects_hostless_url(monkeypatch, tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    monkeypatch.setattr(manual_ingest, "validate_url_safety", lambda _url: None)

    result = service.ingest("https:///path-only")

    assert result["status"] == "error"
    assert "host" in result["message"]


def _stub_enrichers(service, *, content: str, raw_html: str) -> None:
    service.http = SimpleNamespace(
        enrich=lambda _url: {
            "success": True,
            "reason": "html_ok",
            "content": content,
            "raw_content": raw_html,
        }
    )
    service.scholarly = SimpleNamespace(
        enrich_url=lambda _url: {"success": False, "reason": "not_applicable"}
    )
    service.headless = SimpleNamespace(
        enrich=lambda _url, _cfg: {"success": False, "reason": "not_needed"}
    )


def test_ingest_reports_invalid_payload(monkeypatch, tmp_path: Path):
    db = MagicMock()
    db.get_article_by_url.return_value = None
    monkeypatch.setattr(
        manual_ingest,
        "ALL_SOURCES",
        {
            "research_feed": {
                "name": "Research Feed",
                "url": "https://example.org/feed.xml",
                "category": "science",
                "enrichment_strategy": "scholarly",
            }
        },
    )
    monkeypatch.setattr(manual_ingest, "validate_url_safety", lambda _url: None)
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    _stub_enrichers(
        service,
        content=_words(100),
        raw_html=(
            "<html><head>"
            '<meta property="og:title" content="Invalid Payload Probe" />'
            '<meta property="article:published_time" content="2026-05-01T00:00:00Z" />'
            "</head><body><p>Body.</p></body></html>"
        ),
    )

    def _boom(_payload):
        raise ValueError("schema says no")

    monkeypatch.setattr(manual_ingest.CollectorArticleModel, "model_validate", _boom)

    result = service.ingest("https://example.org/feed-ready/article")

    assert result["status"] == "error"
    assert result["message"] == "Payload inválido: schema says no"


def test_ingest_reports_duplicate_race_without_record(monkeypatch, tmp_path: Path):
    db = MagicMock()
    db.get_article_by_url.side_effect = [None, None]
    db.save_article.return_value = None
    monkeypatch.setattr(
        manual_ingest,
        "ALL_SOURCES",
        {
            "research_feed": {
                "name": "Research Feed",
                "url": "https://example.org/feed.xml",
                "category": "science",
                "enrichment_strategy": "scholarly",
            }
        },
    )
    monkeypatch.setattr(manual_ingest, "validate_url_safety", lambda _url: None)
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    _stub_enrichers(
        service,
        content=_words(100),
        raw_html=(
            "<html><head>"
            '<meta property="og:title" content="Duplicate Race Probe Article" />'
            '<meta property="article:published_time" content="2026-05-02T00:00:00Z" />'
            "</head><body><p>Body.</p></body></html>"
        ),
    )

    result = service.ingest("https://example.org/duplicate-race/article")

    assert result["status"] == "error"
    assert "duplicado equivalente" in result["message"]


def test_resolve_reuses_manual_source_entry(monkeypatch, tmp_path: Path):
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    existing_cfg = {
        "name": "foo.example.org",
        "url": "https://other.example.org/",
        "credibility_score": 0.5,
        "tier": "D",
    }
    monkeypatch.setattr(
        manual_ingest, "ALL_SOURCES", {"manual_foo_example_org": existing_cfg}
    )

    source_id, source_cfg, created = service._resolve_or_create_source(
        "https://foo.example.org/article"
    )

    assert (source_id, created) == ("manual_foo_example_org", False)
    assert source_cfg == existing_cfg
    db.initialize_sources.assert_not_called()


def test_build_payload_skips_nondict_metadata(tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    attempts = [
        {
            "method": "http",
            "success": True,
            "reason": "ok",
            "content": _words(100),
            "content_length": 500,
            "metadata": "junk",
        },
        {
            "method": "headless",
            "success": True,
            "reason": "ok",
            "content": None,
            "content_length": 0,
            "metadata": {
                "title": "Junk Skipped Title Here",
                "summary": "Junk skipped summary.",
                "published_date": datetime(2026, 6, 1, tzinfo=timezone.utc),
            },
        },
    ]

    payload, error = service._build_payload(
        "https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config={
            "name": "probe",
            "category": "science",
            "enrichment_strategy": "http",
        },
        source_created=False,
        fetch_attempts=attempts,
    )

    assert error is None
    assert payload is not None
    assert payload["title"] == "Junk Skipped Title Here"


def test_build_payload_derives_summary_and_title(tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    content = _words(100)
    attempts = [
        {
            "method": "http",
            "success": True,
            "reason": "ok",
            "content": content,
            "content_length": len(content),
            "metadata": {
                "authors": ["Probe Author"],
                "published_date": datetime(2026, 6, 2, tzinfo=timezone.utc),
            },
        }
    ]

    payload, error = service._build_payload(
        "https://probe.example.org/some-long-article-slug-here",
        source_id="manual_probe_example_org",
        source_config={
            "name": "probe",
            "category": "science",
            "enrichment_strategy": "http",
        },
        source_created=False,
        fetch_attempts=attempts,
    )

    assert error is None
    assert payload is not None
    assert payload["summary"].startswith("word word")
    assert payload["title"] == "Some Long Article Slug Here"


def test_preferred_method_headless_fallback(tmp_path: Path):
    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)

    assert (
        service._preferred_method({"enrichment_strategy": "headless_fallback"})
        == "http"
    )
    assert (
        service._preferred_method({"enrichment_strategy": "scholarly"}) == "scholarly"
    )
