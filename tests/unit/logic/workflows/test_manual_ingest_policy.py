"""Policy-ownership tests for manual ingest (plan 100, LAW-B3/LAW-B5).

Credibility/tier defaults and word minimums live in CollectionConfig
(``[collection]``); the dateless rule lives in the shared
``infer_manual_published_date`` helper next to PublicationIdentityResolver.
These tests pin that ownership: configured values flow through, and the
dateless rule flags inference while the resolver keeps quarantining
genuinely undated articles.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService
from news_collector.logic.workflows.publication_identity import (
    MANUAL_INGEST_INFERRED_DATE_KEY,
    PublicationIdentityResolver,
    UndatedArticleError,
    infer_manual_published_date,
)


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def _attempts(*, content: str | None, summary: str, published=None) -> list[dict]:
    metadata: dict = {"title": "Policy Probe Article Title", "summary": summary}
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


def _payload(service, **kwargs):
    payload_kwargs = {
        "canonical_url": "https://probe.example.org/article",
        "source_id": "manual_probe_example_org",
        "source_config": _source_config(),
        "source_created": True,
        "fetch_attempts": _attempts(content=_words(100), summary="Probe summary."),
    }
    payload_kwargs.update(kwargs)
    return service._build_payload(**payload_kwargs)


def test_created_source_uses_configured_policy_defaults(monkeypatch, tmp_path: Path):
    """Byte-identical defaults (0.5/"D") arrive via config, not literals."""
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    sources: dict[str, dict] = {}
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES", sources
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.save_sources",
        lambda new_sources: (sources.clear(), sources.update(new_sources)),
    )

    source_id, source_cfg, created = service._resolve_or_create_source(
        "https://www.policy-probe.example.org/article"
    )

    assert created is True
    assert source_cfg["credibility_score"] == 0.5
    assert source_cfg["tier"] == "D"
    assert source_cfg["manual_only"] is True
    db.initialize_sources.assert_called_once_with({source_id: source_cfg})


def test_created_source_honors_explicit_policy_overrides(monkeypatch, tmp_path: Path):
    db = MagicMock()
    service = ManualUrlIngestService(
        db,
        export_dir=tmp_path,
        policy={
            "manual_ingest_source_credibility": 0.9,
            "manual_ingest_source_tier": "C",
        },
    )
    sources: dict[str, dict] = {}
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES", sources
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.save_sources",
        lambda new_sources: (sources.clear(), sources.update(new_sources)),
    )

    _, source_cfg, _ = service._resolve_or_create_source(
        "https://override-probe.example.org/article"
    )

    assert source_cfg["credibility_score"] == 0.9
    assert source_cfg["tier"] == "C"


def test_matched_known_source_keeps_its_own_policy(monkeypatch, tmp_path: Path):
    """Host matching mechanics are untouched: known sources win over policy."""
    db = MagicMock()
    service = ManualUrlIngestService(
        db,
        export_dir=tmp_path,
        policy={
            "manual_ingest_source_credibility": 0.9,
            "manual_ingest_source_tier": "C",
        },
    )
    monkeypatch.setattr(
        "news_collector.logic.workflows.manual_ingest.ALL_SOURCES",
        {
            "known": {
                "name": "Known",
                "url": "https://known.example.org/feed.xml",
                "credibility_score": 0.95,
                "tier": "A",
            }
        },
    )

    source_id, source_cfg, created = service._resolve_or_create_source(
        "https://www.known.example.org/some-article"
    )

    assert (source_id, created) == ("known", False)
    assert source_cfg["credibility_score"] == 0.95
    assert source_cfg["tier"] == "A"
    db.initialize_sources.assert_not_called()


def test_word_gate_honors_configured_minimums(tmp_path: Path):
    db = MagicMock()
    strict = ManualUrlIngestService(
        db, export_dir=tmp_path, policy={"manual_ingest_min_words": 120}
    )
    relaxed = ManualUrlIngestService(
        db, export_dir=tmp_path, policy={"manual_ingest_min_words": 40}
    )
    attempts = _attempts(content=_words(100), summary="Probe summary.")

    strict_payload, strict_error = strict._build_payload(
        "https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        source_created=False,
        fetch_attempts=attempts,
    )
    relaxed_payload, _ = relaxed._build_payload(
        "https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        source_created=False,
        fetch_attempts=attempts,
    )

    assert strict_payload is None
    assert (strict_error or {})["error_code"] == "source_unusable"
    assert relaxed_payload is not None
    assert relaxed_payload["word_count"] == 100


def test_summary_only_branch_honors_configured_minimum(tmp_path: Path):
    db = MagicMock()
    default = ManualUrlIngestService(db, export_dir=tmp_path)
    strict = ManualUrlIngestService(
        db, export_dir=tmp_path, policy={"manual_ingest_summary_min_words": 60}
    )
    attempts = _attempts(content=None, summary=_words(45))

    default_payload, _ = default._build_payload(
        "https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        source_created=False,
        fetch_attempts=attempts,
    )
    strict_payload, strict_error = strict._build_payload(
        "https://probe.example.org/article",
        source_id="manual_probe_example_org",
        source_config=_source_config(),
        source_created=False,
        fetch_attempts=attempts,
    )

    assert default_payload is not None  # 45 >= default 40
    assert default_payload["content_mode"] == "summary_only"
    assert strict_payload is None
    assert (strict_error or {})["error_code"] == "source_unusable"


def test_shared_inference_rule_only_marks_missing_dates():
    present = datetime(2026, 2, 10, tzinfo=timezone.utc)
    assert infer_manual_published_date(present) == (present, False)

    invented, flagged = infer_manual_published_date(None)
    assert flagged is True
    assert isinstance(invented, datetime)


def test_dateless_manual_marks_inference_flag(tmp_path: Path):
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    payload, error = _payload(
        service,
        fetch_attempts=_attempts(content=_words(100), summary="Probe summary."),
    )

    assert error is None
    assert payload is not None
    assert isinstance(payload["published_date"], datetime)
    manual_meta = payload["article_metadata"]["source_metadata"]["manual_ingest"]
    assert manual_meta[MANUAL_INGEST_INFERRED_DATE_KEY] is True


def test_dated_manual_keeps_explicit_date_unflagged(tmp_path: Path):
    db = MagicMock()
    service = ManualUrlIngestService(db, export_dir=tmp_path)
    explicit = datetime(2026, 1, 15, tzinfo=timezone.utc)
    payload, error = _payload(
        service,
        fetch_attempts=_attempts(
            content=_words(100), summary="Probe summary.", published=explicit
        ),
    )

    assert error is None
    assert payload is not None
    assert payload["published_date"] == explicit
    manual_meta = payload["article_metadata"]["source_metadata"]["manual_ingest"]
    assert manual_meta[MANUAL_INGEST_INFERRED_DATE_KEY] is False


def test_resolver_accepts_materialized_date_but_quarantines_undated():
    materialized = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
    assert (
        PublicationIdentityResolver._derive_date(
            {"id": "manual-1", "published_date": materialized}
        )
        == "2026-02-10"
    )
    with pytest.raises(UndatedArticleError):
        PublicationIdentityResolver._derive_date({"id": "manual-2"})
