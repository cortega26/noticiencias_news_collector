"""Unit tests for the webhook contract models (plan 041 coverage gate).

The endpoint-level webhook tests in ``tests/test_webhook.py`` are marked
``pytest.mark.e2e`` and are therefore excluded from the contracts suite;
these pure-model tests keep ``news_collector/contracts/webhook.py`` covered
inside the 80% contracts coverage gate that ``make verify-ci`` enforces.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.contracts.webhook import (
    DiagnosticResult,
    FrontendWebhookEvent,
    PublishCompleteEvent,
    ValidationResultEvent,
    parse_webhook_payload,
)


def _base_payload(event: str = "validation_result") -> dict:
    return {
        "event": event,
        "commit_sha": "abc123",
        "branch": "main",
        "status": "pass",
        "frontend_ref": "refs/heads/main",
        "run_url": "https://github.com/cortega26/noticiencias/actions/runs/1",
        "publication_ids": ["refinery-1"],
    }


def test_validation_result_event_minimal():
    event = ValidationResultEvent.model_validate(_base_payload())
    assert event.event == "validation_result"
    assert event.commit_sha == "abc123"
    assert event.diagnostics == []


def test_publish_complete_event_dispatch():
    event = PublishCompleteEvent.model_validate(_base_payload("publish_complete"))
    assert event.event == "publish_complete"
    assert event.status == "pass"


def test_unknown_event_type_raises_value_error():
    with pytest.raises(ValueError):
        parse_webhook_payload(_base_payload("unknown_event"))


def test_parse_dispatches_validation_result():
    parsed = parse_webhook_payload(_base_payload("validation_result"))
    assert isinstance(parsed, ValidationResultEvent)


def test_parse_dispatches_publish_complete():
    parsed = parse_webhook_payload(_base_payload("publish_complete"))
    assert isinstance(parsed, PublishCompleteEvent)


def test_diagnostic_result_aliases():
    diag = DiagnosticResult(
        check="content-guard",
        status="fail",
        filesCount=3,
        article_count=2,
        deploy_url="https://example.com/deploy",
        errors=["boom"],
    )
    assert diag.filesCount == 3
    assert diag.article_count == 2
    assert diag.deploy_url == "https://example.com/deploy"
    assert diag.errors == ["boom"]


def test_diagnostic_result_populate_by_name_and_alias():
    raw = {
        "check": "pages",
        "status": "pass",
        "filesCount": 1,
    }
    diag = DiagnosticResult.model_validate(raw)
    assert diag.filesCount == 1
    assert diag.model_dump(by_alias=True)["filesCount"] == 1


def test_publication_ids_cap_enforced():
    payload = _base_payload()
    payload["publication_ids"] = [f"id-{i}" for i in range(201)]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)


def test_publication_ids_rejects_empty_strings():
    payload = _base_payload()
    payload["publication_ids"] = ["ok", "", "  "]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)


def test_timestamp_optional_and_parsed():
    payload = _base_payload()
    payload["timestamp"] = "2026-08-10T12:00:00Z"
    event = ValidationResultEvent.model_validate(payload)
    assert event.timestamp is not None
    assert event.timestamp.tzinfo is not None


def test_timestamp_absent_defaults_none():
    event = ValidationResultEvent.model_validate(_base_payload())
    assert event.timestamp is None


def test_frontend_webhook_event_invalid_status_rejected():
    payload = _base_payload()
    payload["status"] = "maybe"
    with pytest.raises(ValidationError):
        FrontendWebhookEvent.model_validate(payload)


def test_missing_required_field_rejected():
    payload = _base_payload()
    del payload["run_url"]
    with pytest.raises(ValidationError):
        ValidationResultEvent.model_validate(payload)
