from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.run_collector as run_collector
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


def _run_export_main(
    monkeypatch: pytest.MonkeyPatch,
    destination: Path,
    article: dict[str, object],
) -> int:
    report = {"selection_results": {"articles": [article]}}
    monkeypatch.setattr(run_collector, "check_dependencies", lambda: True)
    monkeypatch.setattr(run_collector, "run_simple_collection", lambda args: report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_collector.py",
            "--dry-run",
            "--export-json",
            str(destination),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        run_collector.main()
    return int(exc_info.value.code)


def test_export_serialization_failure_exits_nonzero_without_partial_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "articles.json"
    article = {
        "title": "Unserializable metadata",
        "url": "https://example.com/unserializable",
        "metadata": {"invalid": object()},
    }

    exit_code = _run_export_main(monkeypatch, destination, article)

    assert exit_code == 1
    assert not destination.exists()
    assert not destination.with_suffix(".json.tmp").exists()


def test_atomic_replace_failure_preserves_previous_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "articles.json"
    destination.write_text("previous export", encoding="utf-8")
    article = {
        "title": "Valid article",
        "url": "https://example.com/valid",
        "summary": "Summary",
        "metadata": {},
    }

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(run_collector.os, "replace", fail_replace)
    exit_code = _run_export_main(monkeypatch, destination, article)

    assert exit_code == 1
    assert destination.read_text(encoding="utf-8") == "previous export"
    assert not destination.with_suffix(".json.tmp").exists()
