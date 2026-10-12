"""Stamping/projection tests for the adapter choke point (plan 122, LAW-B2).

``with_source_id`` owns ``source_id`` stamping (drift normalization +
workflow echoes); ``project_source`` owns the serving ``{"id","name"}``
projection. Serving outputs must stay byte-identical.
"""

from __future__ import annotations

from types import SimpleNamespace

from news_collector.contracts.adapters import project_source, with_source_id


def test_with_source_id_stamps_without_mutating():
    record = {"status": "error", "source_created": False}
    stamped = with_source_id(record, "manual_probe_example_org")

    assert stamped == {
        "source_id": "manual_probe_example_org",
        "status": "error",
        "source_created": False,
    }
    assert record == {"status": "error", "source_created": False}


def test_with_source_id_preserves_drift_override_order():
    """Drift files are keyed by source_id; an id inside the record wins."""
    raw = {"source_id": "inner_wins", "save_ratio": 0.5}
    assert with_source_id(raw, "outer_key") == {
        "source_id": "inner_wins",
        "save_ratio": 0.5,
    }
    assert with_source_id({"save_ratio": 0.5}, "outer_key") == {
        "source_id": "outer_key",
        "save_ratio": 0.5,
    }


def test_manual_prefix_rules_flow_through_helper(monkeypatch, tmp_path):
    """The manual_ host rule resolves identically; echoes carry it via helper."""
    from unittest.mock import MagicMock

    from news_collector.logic.workflows import manual_ingest
    from news_collector.logic.workflows.manual_ingest import ManualUrlIngestService

    sources: dict[str, dict] = {}
    monkeypatch.setattr(manual_ingest, "ALL_SOURCES", sources)
    monkeypatch.setattr(
        manual_ingest,
        "save_sources",
        lambda new_sources: (sources.clear(), sources.update(new_sources)),
    )

    service = ManualUrlIngestService(MagicMock(), export_dir=tmp_path)
    source_id, _, created = service._resolve_or_create_source(
        "https://www.stampprobe.example.org/article"
    )
    assert created is True
    assert source_id == "manual_stampprobe_example_org"

    stamped = with_source_id({"status": "error"}, source_id)
    assert stamped["source_id"] == "manual_stampprobe_example_org"


def test_project_source_matches_inline_projection():
    row = SimpleNamespace(source_id="nature", source_name="Nature")
    assert project_source(row) == {"id": "nature", "name": "Nature"}


def test_project_source_related_response_byte_identical():
    from news_collector.serving.api import RelatedSourceResponse

    item = SimpleNamespace(source_id="nature", source_name="Nature")
    via_helper = RelatedSourceResponse(**project_source(item))
    via_inline = RelatedSourceResponse(id=item.source_id, name=item.source_name)

    assert via_helper.model_dump() == via_inline.model_dump()
