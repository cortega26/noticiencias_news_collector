from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import apps.refinery.main as refinery_main
from news_collector.config import settings as config_settings


class _DummyConfigWriter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_value(self, *_args, **_kwargs):
        return None


class _DummyRepo:
    def config_writer(self):
        return _DummyConfigWriter()


def test_main_article_url_uses_manual_ingest_export_and_normal_processing(
    tmp_path: Path, monkeypatch
):
    export_path = tmp_path / "manual_article_77.json"
    export_path.write_text('{"articles": []}', encoding="utf-8")

    config = SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://github.com/org/source",
            target_repo_url="https://github.com/org/target",
            user_name="Refinery Bot",
            user_email="bot@example.com",
        ),
        ollama=SimpleNamespace(api_url="http://ollama.local"),
    )
    db_manager = MagicMock()
    git_handler = MagicMock()
    engine = MagicMock()
    engine.process_articles.return_value = {"processed_count": 1, "errors": []}

    class FakeManualUrlIngestService:
        def __init__(self, db_manager_arg, *, export_dir=None):
            self.db_manager_arg = db_manager_arg
            self.export_dir = export_dir

        def ingest(self, article_url):
            assert article_url == "https://example.org/manual-77"
            return {
                "status": "success",
                "article_id": 77,
                "source_id": "manual_example_org",
                "source_created": True,
                "article_exists": False,
                "published": False,
                "export_path": str(export_path),
                "fetch_attempts": [{"method": "http", "success": True}],
                "article": {"id": 77, "title": "Manual article"},
            }

    monkeypatch.setattr(refinery_main, "load_config", lambda: config)
    monkeypatch.setattr(refinery_main, "preflight_llm_provider", lambda **_kwargs: [])
    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(refinery_main, "DatabaseManager", lambda: db_manager)
    monkeypatch.setattr(refinery_main, "GitHubPublisher", lambda _token: git_handler)
    monkeypatch.setattr(
        refinery_main,
        "resolve_ollama_stage_models",
        lambda _config, logger=None: {
            "default": "main-model",
            "translator": "translator-model",
            "editor": "editor-model",
            "headlines": "headlines-model",
        },
    )
    monkeypatch.setattr(refinery_main, "EditorAgent", lambda **_kwargs: MagicMock())
    monkeypatch.setattr(refinery_main, "RefineryEngine", lambda **_kwargs: engine)
    monkeypatch.setattr(
        refinery_main,
        "ManualUrlIngestService",
        FakeManualUrlIngestService,
    )
    monkeypatch.setattr(
        refinery_main,
        "_select_export_articles",
        lambda *args, **kwargs: (
            [
                {
                    "id": 77,
                    "title": "Manual article",
                    "url": "https://example.org/manual-77",
                    "summary": "Valid summary for refinery processing.",
                    "content": "Valid content for refinery processing." * 10,
                    "source_id": "manual_example_org",
                    "source_name": "example.org",
                    "category": "multidisciplinary",
                    "published_date": "2026-03-01T00:00:00+00:00",
                }
            ],
            export_path,
        ),
    )
    monkeypatch.setattr(refinery_main.git, "Repo", lambda _path: _DummyRepo())
    monkeypatch.setattr(refinery_main, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(refinery_main, "TARGET_DIR", tmp_path / "target")

    result = refinery_main.main(article_url="https://example.org/manual-77")

    assert result["status"] == "success"
    assert result["processed_count"] == 1
    assert result["article_id"] == 77
    assert result["source_id"] == "manual_example_org"
    git_handler.clone_repo.assert_called_once_with(
        config.github.target_repo_url,
        tmp_path / "target",
    )
    engine.process_articles.assert_called_once()
    processed_articles = engine.process_articles.call_args.args[0]
    assert processed_articles[0]["id"] == 77


def test_main_article_url_propagates_processing_error_code(tmp_path: Path, monkeypatch):
    export_path = tmp_path / "manual_article_77.json"
    export_path.write_text('{"articles": []}', encoding="utf-8")

    config = SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://github.com/org/source",
            target_repo_url="https://github.com/org/target",
            user_name="Refinery Bot",
            user_email="bot@example.com",
        ),
        ollama=SimpleNamespace(api_url="http://ollama.local"),
    )
    db_manager = MagicMock()
    git_handler = MagicMock()
    engine = MagicMock()
    engine.process_articles.return_value = {
        "processed_count": 0,
        "errors": [
            {
                "id": "77",
                "message": "Generated article body contains placeholder/error language and cannot be published.",
                "error_code": "editorial_placeholder_blocked",
            }
        ],
    }

    class FakeManualUrlIngestService:
        def __init__(self, db_manager_arg, *, export_dir=None):
            self.db_manager_arg = db_manager_arg
            self.export_dir = export_dir

        def ingest(self, article_url):
            assert article_url == "https://example.org/manual-77"
            return {
                "status": "success",
                "article_id": 77,
                "source_id": "manual_example_org",
                "source_created": True,
                "article_exists": False,
                "published": False,
                "export_path": str(export_path),
                "fetch_attempts": [{"method": "http", "success": True}],
                "article": {"id": 77, "title": "Manual article"},
            }

    monkeypatch.setattr(refinery_main, "load_config", lambda: config)
    monkeypatch.setattr(refinery_main, "preflight_llm_provider", lambda **_kwargs: [])
    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(refinery_main, "DatabaseManager", lambda: db_manager)
    monkeypatch.setattr(refinery_main, "GitHubPublisher", lambda _token: git_handler)
    monkeypatch.setattr(
        refinery_main,
        "resolve_ollama_stage_models",
        lambda _config, logger=None: {
            "default": "main-model",
            "translator": "translator-model",
            "editor": "editor-model",
            "headlines": "headlines-model",
        },
    )
    monkeypatch.setattr(refinery_main, "EditorAgent", lambda **_kwargs: MagicMock())
    monkeypatch.setattr(refinery_main, "RefineryEngine", lambda **_kwargs: engine)
    monkeypatch.setattr(
        refinery_main,
        "ManualUrlIngestService",
        FakeManualUrlIngestService,
    )
    monkeypatch.setattr(
        refinery_main,
        "_select_export_articles",
        lambda *args, **kwargs: (
            [
                {
                    "id": 77,
                    "title": "Manual article",
                    "url": "https://example.org/manual-77",
                    "summary": "Valid summary for refinery processing.",
                    "content": "Valid content for refinery processing." * 10,
                    "source_id": "manual_example_org",
                    "source_name": "example.org",
                    "category": "multidisciplinary",
                    "published_date": "2026-03-01T00:00:00+00:00",
                }
            ],
            export_path,
        ),
    )
    monkeypatch.setattr(refinery_main.git, "Repo", lambda _path: _DummyRepo())
    monkeypatch.setattr(refinery_main, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(refinery_main, "TARGET_DIR", tmp_path / "target")

    result = refinery_main.main(article_url="https://example.org/manual-77")

    assert result["status"] == "error"
    assert result["processed_count"] == 0
    assert result["error_code"] == "editorial_placeholder_blocked"
    assert result["article_id"] == 77
    assert "placeholder/error language" in result["message"]


def test_main_fails_fast_when_llm_preflight_fails(monkeypatch) -> None:
    config = SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://github.com/org/source",
            target_repo_url="https://github.com/org/target",
            user_name="Refinery Bot",
            user_email="bot@example.com",
        ),
        ollama=SimpleNamespace(api_url="http://ollama.local"),
    )
    db_ctor = MagicMock()
    editor_ctor = MagicMock()

    monkeypatch.setattr(refinery_main, "load_config", lambda: config)
    monkeypatch.setattr(
        refinery_main,
        "preflight_llm_provider",
        lambda **_kwargs: [
            "Ollama generate probe failed: Ollama request failed for model "
            "'qwen2.5:32b' (status 500): model requires more system memory "
            "(19.1 GiB) than is available (1.0 GiB)"
        ],
    )
    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", False)
    monkeypatch.setattr(refinery_main, "DatabaseManager", db_ctor)
    monkeypatch.setattr(refinery_main, "EditorAgent", editor_ctor)

    result = refinery_main.main()

    assert result["status"] == "error"
    assert result["error_code"] == "llm_preflight_failed"
    assert "requires more system memory" in result["message"]
    assert db_ctor.call_count == 0
    assert editor_ctor.call_count == 0


def test_main_refreshes_runtime_config_and_passes_same_config_to_editor_agent(
    tmp_path: Path, monkeypatch
) -> None:
    config = SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://github.com/org/source",
            target_repo_url="https://github.com/org/target",
            user_name="Refinery Bot",
            user_email="bot@example.com",
        ),
        ollama=SimpleNamespace(api_url="http://ollama.local"),
    )
    db_manager = MagicMock()
    engine = MagicMock()
    engine.process_articles.return_value = {"processed_count": 0, "errors": []}
    refreshed: list[object] = []
    editor_kwargs: dict[str, object] = {}

    monkeypatch.setattr(refinery_main, "load_config", lambda: config)
    monkeypatch.setattr(
        config_settings,
        "refresh_runtime_config",
        lambda cfg=None: refreshed.append(cfg or config) or (cfg or config),
    )
    monkeypatch.setattr(refinery_main, "preflight_llm_provider", lambda **_kwargs: [])
    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(refinery_main, "DatabaseManager", lambda: db_manager)
    monkeypatch.setattr(refinery_main, "GitHubPublisher", lambda _token: MagicMock())
    monkeypatch.setattr(
        refinery_main,
        "resolve_ollama_stage_models",
        lambda _config, logger=None: {
            "default": "main-model",
            "translator": "translator-model",
            "editor": "editor-model",
            "headlines": "headlines-model",
        },
    )
    monkeypatch.setattr(
        refinery_main,
        "EditorAgent",
        lambda **kwargs: editor_kwargs.update(kwargs) or MagicMock(),
    )
    monkeypatch.setattr(refinery_main, "RefineryEngine", lambda **_kwargs: engine)
    monkeypatch.setattr(
        refinery_main, "run_collector_script", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        refinery_main,
        "_safe_clone_source_repo",
        lambda *_args, **_kwargs: tmp_path / "source",
    )
    monkeypatch.setattr(
        refinery_main,
        "_select_export_articles",
        lambda *args, **kwargs: ([], None),
    )
    monkeypatch.setattr(refinery_main, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(refinery_main, "TARGET_DIR", tmp_path / "target")

    result = refinery_main.main(fetch_only=True)

    assert result["status"] == "success"
    assert refreshed == [config]
    assert editor_kwargs["config"] is config
