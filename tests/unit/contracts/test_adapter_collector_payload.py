"""Parity tests for the adapter-owned collector payload (plan 122, LAW-B2).

``build_collector_payload`` owns the CollectorArticleModel input shape;
``ManualUrlIngestService._build_payload`` keeps fetch-merge only. These tests
pin byte-identical equivalence between the builder and the workflow path on
recorded fixtures (pre- AND post-switch).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from news_collector.contracts.adapters import build_collector_payload


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def _attempts(*, content: str | None, summary: str, published=None) -> list[dict]:
    metadata: dict = {"title": "Parity Probe Article Title", "summary": summary}
    if published is not None:
        metadata["published_date"] = published
    return [
        {
            "method": "http",
            "success": True,
            "reason": "ok",
            "content": content,
            "content_length": len(content or ""),
            "metadata": metadata,
        }
    ]


def _source_config() -> dict:
    return {
        "name": "probe.example.org",
        "url": "https://probe.example.org/",
        "category": "science",
        "enrichment_strategy": "http",
    }


def _builder_from_old(old_payload: dict, *, source_config: dict) -> dict:
    """Decompose the workflow payload back into typed builder inputs."""
    article_metadata = old_payload["article_metadata"]
    return build_collector_payload(
        canonical_url=old_payload["url"],
        title=old_payload["title"],
        summary=old_payload["summary"],
        content=old_payload["content"],
        source_id=old_payload["source_id"],
        source_config=source_config,
        published_date=old_payload["published_date"],
        authors=old_payload["authors"],
        language=old_payload["language"],
        doi=old_payload["doi"],
        journal=old_payload["journal"],
        is_preprint=old_payload["is_preprint"],
        word_count=old_payload["word_count"],
        reading_time_minutes=old_payload["reading_time_minutes"],
        content_mode=old_payload["content_mode"],
        image_url=article_metadata["image_url"],
        source_metadata=article_metadata["source_metadata"],
        processing_timestamp=article_metadata["processing_timestamp"],
    )


def _check_parity(service, *, canonical_url, source_id, source_config, fetch_attempts):
    from news_collector.contracts.collector import CollectorArticleModel

    old_payload, error = service._build_payload(
        canonical_url,
        source_id=source_id,
        source_config=source_config,
        source_created=False,
        fetch_attempts=fetch_attempts,
    )
    assert error is None
    assert old_payload is not None
    # Old path output must validate (sanity: fixture is realistic).
    CollectorArticleModel.model_validate(old_payload)
    rebuilt = _builder_from_old(old_payload, source_config=source_config)
    assert rebuilt == old_payload
    # Builder output must validate identically.
    CollectorArticleModel.model_validate(rebuilt)
    return old_payload


def test_builder_matches_workflow_full_text(tmp_path: Path):
    from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService

    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    explicit = datetime(2026, 1, 15, tzinfo=timezone.utc)
    _check_parity(
        service,
        canonical_url="https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        fetch_attempts=_attempts(
            content=_words(100), summary="Probe summary.", published=explicit
        ),
    )


def test_builder_matches_workflow_summary_only(tmp_path: Path):
    from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService

    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    _check_parity(
        service,
        canonical_url="https://probe.example.org/summary-article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        fetch_attempts=_attempts(content=None, summary=_words(45)),
    )


def test_builder_matches_workflow_inferred_date(tmp_path: Path):
    from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService

    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    payload = _check_parity(
        service,
        canonical_url="https://probe.example.org/dateless",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        fetch_attempts=_attempts(content=_words(100), summary="Probe summary."),
    )
    assert isinstance(payload["published_date"], datetime)


def test_builder_source_fallbacks_match_workflow(tmp_path: Path):
    from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService

    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    bare_config: dict = {"url": "https://bare.example.org/"}
    payload = _check_parity(
        service,
        canonical_url="https://bare.example.org/article",
        source_id="manual_bare_example_org",
        source_config=bare_config,
        fetch_attempts=_attempts(
            content=_words(100),
            summary="Probe summary.",
            published=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    )
    assert payload["source_name"] == "manual_bare_example_org"
    assert payload["category"] == "multidisciplinary"
