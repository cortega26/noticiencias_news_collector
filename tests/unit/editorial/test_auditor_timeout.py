from __future__ import annotations

import json
from unittest.mock import MagicMock
from pathlib import Path
from types import SimpleNamespace

import requests
from news_collector.components.editorial.auditor import EditorialAuditor


def test_auditor_timeout_returns_non_fatal_failed_status(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_model_for_stage",
        lambda *args, **kwargs: "registry-auditor:13b",
    )

    cfg = SimpleNamespace(
        editorial_auditor=SimpleNamespace(
            enabled=True,
            sampling_rate=1.0,
            blocking=False,
            timeout_seconds=5,
            max_retries=2,
            health_timeout_seconds=1,
        ),
        paths=SimpleNamespace(data_dir=tmp_path),
        ollama=SimpleNamespace(api_url="http://localhost:11434/api/generate"),
    )
    auditor = EditorialAuditor(cfg)

    monkeypatch.setattr(
        auditor.provider, "check_health", lambda timeout_seconds: (True, "ok")
    )

    def _raise_timeout(*args, **kwargs):
        raise requests.Timeout("Read timed out")

    monkeypatch.setattr(auditor.provider, "generate_sync", _raise_timeout)

    result = auditor.audit_article_sync(
        article_id="1087",
        content="Contenido de prueba",
        source_url="https://example.com/article-1087",
        article_data={"title": "Timeout test"},
    )

    assert result["status"] == "audit_failed"
    assert "timeout" in result["reason"]
    assert result["attempts"] == 3

    status_file = tmp_path / "article_metadata" / "1087" / "auditor_status.json"
    status_payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert status_payload["status"] == "audit_failed"


def test_optional_auditor_timeout_uses_warning_not_error(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_model_for_stage",
        lambda *args, **kwargs: "registry-auditor:13b",
    )

    cfg = SimpleNamespace(
        editorial_auditor=SimpleNamespace(
            enabled=True,
            sampling_rate=1.0,
            blocking=False,
            timeout_seconds=5,
            max_retries=2,
            health_timeout_seconds=1,
        ),
        paths=SimpleNamespace(data_dir=tmp_path),
        ollama=SimpleNamespace(api_url="http://localhost:11434/api/generate"),
    )
    auditor = EditorialAuditor(cfg)
    monkeypatch.setattr(
        auditor.provider, "check_health", lambda timeout_seconds: (True, "ok")
    )

    def _raise_timeout(*args, **kwargs):
        raise requests.Timeout("Read timed out")

    monkeypatch.setattr(auditor.provider, "generate_sync", _raise_timeout)

    warn_mock = MagicMock()
    error_mock = MagicMock()
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.logger.warning", warn_mock
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.logger.error", error_mock
    )

    result = auditor.audit_article_sync(
        article_id="1088",
        content="Contenido de prueba",
        source_url="https://example.com/article-1088",
        article_data={"title": "Timeout severity test"},
    )

    assert result["status"] == "audit_failed"
    assert any(
        "Auditor Error for 1088" in str(call.args[0])
        for call in warn_mock.call_args_list
    )
    assert not any(
        "Auditor Error for 1088" in str(call.args[0])
        for call in error_mock.call_args_list
    )


def test_keyword_word_boundary_matching(monkeypatch, tmp_path: Path) -> None:
    """'cura' must not match inside 'oscura'; standalone 'cura' must still trigger."""
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_model_for_stage",
        lambda *args, **kwargs: "registry-auditor:13b",
    )
    monkeypatch.setattr(
        "news_collector.components.editorial.auditor.get_provider",
        lambda *args, **kwargs: MagicMock(),
    )

    cfg = SimpleNamespace(
        editorial_auditor=SimpleNamespace(
            enabled=True,
            sampling_rate=0.0,
            blocking=False,
            timeout_seconds=5,
            max_retries=2,
            health_timeout_seconds=1,
        ),
        paths=SimpleNamespace(data_dir=tmp_path),
        ollama=SimpleNamespace(api_url="http://localhost:11434/api/generate"),
    )
    auditor = EditorialAuditor(cfg)

    article = {"category": "astronomy", "metadata": {}}

    # "oscura" contains "cura" as substring — must NOT trigger
    assert not auditor.should_run_fast(
        article,
        "la materia oscura del universo y la energia oscura cosmica",
    )

    # standalone "cura" — must trigger
    assert auditor.should_run_fast(
        article,
        "una nueva cura para la enfermedad fue descubierta",
    )
