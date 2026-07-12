from __future__ import annotations

from datetime import datetime, timezone

from scripts.run_collector import _serialize_export_article


def test_serialize_export_article_accepts_dry_run_mapping() -> None:
    published = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    article = {
        "id": 7,
        "title": "Portable dry-run export",
        "url": "https://example.com/article",
        "summary": "Summary",
        "content": "Body",
        "source_name": "Example",
        "source_id": "example",
        "published_date": published,
        "metadata": {"image_url": "https://example.com/image.jpg"},
        "authors": ["Author"],
        "category": "technology",
        "score": 0.9,
    }

    serialized = _serialize_export_article(article)

    assert serialized["published_date"] == published.isoformat()
    assert serialized["source_id"] == "example"
    assert serialized["image_url"] == "https://example.com/image.jpg"
    assert serialized["score"] == 0.9


class _MetadataModel:
    def model_dump(self, *, mode: str) -> dict[str, str]:
        assert mode == "json"
        return {"image_url": "https://example.com/model-image.jpg"}


def test_serialize_export_article_normalizes_metadata_model() -> None:
    article = {
        "title": "Structured metadata",
        "url": "https://example.com/structured",
        "metadata": _MetadataModel(),
    }

    serialized = _serialize_export_article(article)

    assert serialized["metadata"] == {
        "image_url": "https://example.com/model-image.jpg"
    }
    assert serialized["image_url"] == "https://example.com/model-image.jpg"


def test_serialize_export_article_derives_missing_summary_from_content() -> None:
    article = {
        "title": "Content-only source",
        "url": "https://example.com/content-only",
        "summary": "",
        "content": "  Evidence-backed content.  ",
    }

    serialized = _serialize_export_article(article)

    assert serialized["summary"] == "Evidence-backed content."
