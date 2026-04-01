import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.refinery.main import _load_export_articles
from news_collector.config.sources import ALL_SOURCES
from news_collector.contracts.collector import CollectorArticleModel
from news_collector.logic.workflows.refinery_engine import RefineryEngine


class _DummyDB:
    def is_article_published(self, _article_id: int) -> bool:
        return False


def _build_engine_with_mocks(data_dir: Path):
    mock_db = MagicMock()
    mock_db.get_canonical_slug.return_value = None

    mock_git = MagicMock()
    mock_git.create_branch.return_value = "content/update/2024-01-01-audit-160"
    mock_git.create_pull_request.return_value = "https://example.test/pr/160"

    mock_editor = MagicMock()
    mock_editor.process_article.return_value = (
        '---\nslug: audit-160\nrefinery_id: "160"\n---\n\nContenido auditado.'
    )

    config = SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled", editorial_mode="standard"
        ),
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
        paths=SimpleNamespace(data_dir=str(data_dir)),
    )
    from news_collector.contracts.collector import CollectorArticleModel

    def validate_collector_payload(payload):
        return CollectorArticleModel.model_validate(payload).model_dump()

    engine = RefineryEngine(
        mock_db,
        mock_git,
        mock_editor,
        config,
        contract_validator=validate_collector_payload,
    )
    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {
        "epistemic_rigor_score": 10.0,
        "has_proper_caveats": True,
    }
    engine.auditor.should_run_fast.return_value = False
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False

    return engine, mock_db, mock_git, mock_editor


def test_legacy_export_to_pr_golden_path_preserves_source_identity(tmp_path: Path):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    canonical_source_name = str(source_cfg["name"]).strip()

    export_path = tmp_path / "latest_articles.json"
    export_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "news_collector.export.v1",
                "articles": [
                    {
                        "id": 160,
                        "title": "Legacy payload for end-to-end refinery hardening test",
                        "url": "https://example.com/article-160",
                        "summary": "Valid summary for refinery hardening validation.",
                        "content": "Valid content body for refinery hardening validation.",
                        "source_name": canonical_source_name.upper(),
                        "category": "science",
                        "published_date": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_export_articles(export_path, _DummyDB(), process_id="160")
    assert len(loaded) == 1
    normalized = loaded[0]
    assert normalized["source_id"] == source_id
    assert normalized["source_name"] == canonical_source_name

    model = CollectorArticleModel.model_validate(normalized)
    assert model.source_id == source_id
    assert model.source_name == canonical_source_name
    assert model.published_date.tzinfo == timezone.utc

    engine, _mock_db, mock_git, mock_editor = _build_engine_with_mocks(tmp_path)
    result = engine.process_single_article(normalized, MagicMock(), tmp_path / "target")

    assert result is True
    assert mock_editor.process_article.call_count == 1
    editor_payload = mock_editor.process_article.call_args.args[0]
    assert editor_payload["source_id"] == source_id
    assert editor_payload["source_name"] == canonical_source_name
    assert mock_git.create_pull_request.call_count == 1
    pr_body = mock_git.create_pull_request.call_args.kwargs["body"]
    assert f"Source ID: {source_id}" in pr_body
    assert f"Source Name: {canonical_source_name}" in pr_body


def test_refinery_rejects_payload_if_source_id_is_removed(tmp_path: Path):
    source_id, source_cfg = next(
        (sid, cfg)
        for sid, cfg in ALL_SOURCES.items()
        if str(cfg.get("name", "")).strip()
    )
    canonical_source_name = str(source_cfg["name"]).strip()

    article = {
        "id": 160,
        "title": "Contract payload missing source_id must be rejected",
        "url": "https://example.com/article-160",
        "summary": "Valid summary for contract rejection path.",
        "content": "Valid content for contract rejection path.",
        "source_name": canonical_source_name,
        "category": "science",
        "published_date": datetime.now(timezone.utc).isoformat(),
        "source_id": source_id,
    }
    article.pop("source_id")

    engine, _mock_db, mock_git, mock_editor = _build_engine_with_mocks(tmp_path)
    result = engine.process_single_article(article, MagicMock(), tmp_path / "target")

    assert result is False
    assert mock_editor.process_article.call_count == 0
    assert mock_git.create_branch.call_count == 0
    assert mock_git.create_pull_request.call_count == 0
