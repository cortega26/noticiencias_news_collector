"""Plan 149 item 1: `run_publication_pipeline` owns the engine lifecycle.

The engine builds a one-worker `ThreadPoolExecutor` in `__init__`; the
pipeline is its production owner and must release it on *every* return
path (success, early no-op, crash), not just the happy path. These tests
stub every collaborator and assert `engine.close()` on two representative
return paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import news_collector.logic.workflows.publication_pipeline as pipeline
from news_collector.logic.workflows.publication_pipeline import run_publication_pipeline


@pytest.fixture()
def stub_pipeline(monkeypatch, tmp_path):
    """Stub the pipeline's collaborators; return (engine, db, source_dir)."""
    engine = MagicMock()
    from news_collector.storage.database import DatabaseManager

    db = DatabaseManager({"type": "sqlite", "path": tmp_path / "lifecycle.db"})
    source_dir = tmp_path / "source"
    (source_dir / "data").mkdir(parents=True, exist_ok=True)

    config = SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://example.invalid/source.git",
            target_repo_url="https://example.invalid/target.git",
            user_name="Test Publisher",
            user_email="publisher@example.invalid",
        ),
        ollama=SimpleNamespace(api_url="http://example.invalid"),
        app=SimpleNamespace(editorial_mode="standard"),
    )
    monkeypatch.setattr(pipeline, "load_config", lambda: config)
    monkeypatch.setattr(pipeline, "GitHubPublisher", lambda token: MagicMock())
    monkeypatch.setattr(
        pipeline,
        "resolve_ollama_stage_models",
        lambda cfg, logger=None: {
            "default": "m",
            "translator": "m",
            "editor": "m",
            "headlines": "m",
            "enrichment": "m",
        },
    )
    monkeypatch.setattr(pipeline, "EditorAgent", lambda **kwargs: MagicMock())
    monkeypatch.setattr(pipeline, "DatabaseManager", lambda *a, **k: db)
    monkeypatch.setattr(pipeline, "RefineryEngine", lambda **kwargs: engine)
    monkeypatch.setattr(pipeline, "preflight_llm_provider", lambda **kwargs: [])
    monkeypatch.setattr(pipeline, "run_collector_script", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_safe_clone_source_repo", lambda *a, **k: source_dir)
    monkeypatch.setattr(
        pipeline,
        "_provision_target_repo",
        lambda *a, **k: (MagicMock(), tmp_path / "target"),
    )
    monkeypatch.setattr(pipeline, "project_root", tmp_path)
    monkeypatch.setattr(pipeline, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(pipeline, "TARGET_DIR", tmp_path / "target")

    from news_collector.config import settings as config_settings

    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(config_settings, "refresh_runtime_config", lambda cfg: None)
    yield engine, db, source_dir
    db.close()


def test_engine_is_closed_on_the_no_candidates_early_return(
    stub_pipeline, monkeypatch
) -> None:
    engine, _db, _source_dir = stub_pipeline

    result = run_publication_pipeline()

    assert result["status"] == "noop"
    engine.close.assert_called_once_with()


def test_engine_is_closed_when_the_run_crashes(stub_pipeline) -> None:
    engine, _db, source_dir = stub_pipeline
    engine.process_articles.side_effect = RuntimeError("boom")
    (source_dir / "data" / "article.md").write_text(
        "# Titular\n\nCuerpo del artículo.", encoding="utf-8"
    )

    result = run_publication_pipeline(process_new_content=True)

    assert result["status"] == "error"
    assert "boom" in result["message"]
    engine.process_articles.assert_called_once()
    engine.close.assert_called_once_with()
