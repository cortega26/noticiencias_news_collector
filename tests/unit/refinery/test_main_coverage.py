"""Coverage tests for apps/refinery/main.py.

Targets the branches not exercised by the existing refinery test files:
slug uniqueness, lock-error handling, export loading edge cases, export
selection fallbacks, run_collector_script execution modes, main() error
paths, the file-scan fallback, delete_article, and main() success paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import apps.refinery.main as ref_main
from news_collector.config import settings as config_settings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        github=SimpleNamespace(
            token="token",
            source_repo_url="https://github.com/org/source",
            target_repo_url="https://github.com/org/target",
            user_name="Refinery Bot",
            user_email="bot@example.com",
        ),
        ollama=SimpleNamespace(api_url="http://ollama.local"),
    )


def _valid_article(i: int = 77) -> dict:
    return {
        "id": i,
        "title": f"Refinery coverage article {i}",
        "url": f"https://example.org/refinery-{i}",
        "summary": "Valid summary for refinery coverage processing.",
        "content": "Valid content for refinery coverage processing." * 10,
        "source_id": "manual_example_org",
        "source_name": "example.org",
        "category": "multidisciplinary",
        "published_date": "2026-03-01T00:00:00+00:00",
    }


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


def _patch_main_deps(monkeypatch, tmp_path: Path) -> dict:
    """Patch every dependency main() constructs; return handles for overrides."""
    config = _config()
    db = MagicMock()
    git_handler = MagicMock()
    engine = MagicMock()
    engine.process_articles.return_value = {"processed_count": 1, "errors": []}
    captured: dict = {}

    monkeypatch.setattr(ref_main, "load_config", lambda: config)
    monkeypatch.setattr(config_settings, "refresh_runtime_config", lambda cfg=None: cfg)
    monkeypatch.setattr(config_settings, "LLM_SYSTEM_AVAILABLE", True)
    monkeypatch.setattr(ref_main, "preflight_llm_provider", lambda **_kwargs: [])
    monkeypatch.setattr(ref_main, "DatabaseManager", lambda: db)
    monkeypatch.setattr(ref_main, "GitHubPublisher", lambda _token: git_handler)
    monkeypatch.setattr(
        ref_main,
        "resolve_ollama_stage_models",
        lambda _config, logger=None: {
            "default": "main-model",
            "translator": "translator-model",
            "editor": "editor-model",
            "headlines": "headlines-model",
            "enrichment": "enrichment-model",
        },
    )
    monkeypatch.setattr(ref_main, "EditorAgent", lambda **_kwargs: MagicMock())

    def _engine_factory(**kwargs):
        captured["engine_kwargs"] = kwargs
        return engine

    monkeypatch.setattr(ref_main, "RefineryEngine", _engine_factory)
    monkeypatch.setattr(ref_main, "run_collector_script", lambda *_a, **_k: None)
    monkeypatch.setattr(ref_main, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(ref_main, "TARGET_DIR", tmp_path / "target")

    def _no_articles(*_a, **_k):
        return [], None

    monkeypatch.setattr(ref_main, "_select_export_articles", _no_articles)

    return {"config": config, "db": db, "git_handler": git_handler, "engine": engine}


# ---------------------------------------------------------------------------
# _is_file_lock_error
# ---------------------------------------------------------------------------


class TestIsFileLockError:
    def test_winerror_32(self):
        exc = SimpleNamespace(winerror=32)
        assert ref_main._is_file_lock_error(exc) is True

    def test_english_message(self):
        exc = RuntimeError("The file is being used by another process")
        assert ref_main._is_file_lock_error(exc) is True

    def test_spanish_message(self):
        exc = RuntimeError("El archivo está siendo utilizado por otro proceso")
        assert ref_main._is_file_lock_error(exc) is True

    def test_unrelated_message(self):
        exc = RuntimeError("disk full")
        assert ref_main._is_file_lock_error(exc) is False


# ---------------------------------------------------------------------------
# _unique_post_slug
# ---------------------------------------------------------------------------


class TestUniquePostSlug:
    def test_base_slug_available(self, tmp_path):
        slug, path = ref_main._unique_post_slug(
            posts_dir=tmp_path,
            date_str="2026-01-01",
            base_slug="science",
            article_id="10",
        )
        assert slug == "science"
        assert path == tmp_path / "2026-01-01-science.md"

    def test_suffix_collision_resolved(self, tmp_path):
        (tmp_path / "2026-01-01-science.md").touch()
        slug, path = ref_main._unique_post_slug(
            posts_dir=tmp_path,
            date_str="2026-01-01",
            base_slug="science",
            article_id="42",
        )
        assert slug == "science-42"
        assert path == tmp_path / "2026-01-01-science-42.md"

    def test_empty_article_id_uses_uuid(self, tmp_path):
        (tmp_path / "2026-01-01-science.md").touch()
        with patch("apps.refinery.main.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "abcdef123456"
            slug, _ = ref_main._unique_post_slug(
                posts_dir=tmp_path,
                date_str="2026-01-01",
                base_slug="science",
                article_id="!!!",
            )
        assert slug == "science-abcdef"

    def test_numeric_attempt_loop(self, tmp_path):
        (tmp_path / "2026-01-01-science.md").touch()
        for suffix in ("42", "42-2", "42-3", "42-4"):
            (tmp_path / f"2026-01-01-science-{suffix}.md").touch()
        slug, path = ref_main._unique_post_slug(
            posts_dir=tmp_path,
            date_str="2026-01-01",
            base_slug="science",
            article_id="42",
        )
        assert slug == "science-42-5"
        assert path == tmp_path / "2026-01-01-science-42-5.md"

    def test_exhausted_raises(self, tmp_path):
        (tmp_path / "2026-01-01-science.md").touch()
        (tmp_path / "2026-01-01-science-42.md").touch()
        for attempt in range(2, 100):
            (tmp_path / f"2026-01-01-science-42-{attempt}.md").touch()
        with pytest.raises(RuntimeError, match="Unable to generate unique slug"):
            ref_main._unique_post_slug(
                posts_dir=tmp_path,
                date_str="2026-01-01",
                base_slug="science",
                article_id="42",
            )


# ---------------------------------------------------------------------------
# _safe_clone_source_repo
# ---------------------------------------------------------------------------


class TestSafeCloneSourceRepo:
    def test_clone_success(self, tmp_path):
        handler = MagicMock()
        result = ref_main._safe_clone_source_repo(handler, "https://x", tmp_path)
        assert result == tmp_path
        handler.clone_repo.assert_called_once()

    def test_lock_error_reuses_existing_clone(self, tmp_path):
        (tmp_path / ".git").mkdir()
        handler = MagicMock()
        handler.clone_repo.side_effect = RuntimeError("being used by another process")
        result = ref_main._safe_clone_source_repo(handler, "https://x", tmp_path)
        assert result == tmp_path

    def test_non_lock_error_raises(self, tmp_path):
        handler = MagicMock()
        handler.clone_repo.side_effect = RuntimeError("auth failed")
        with pytest.raises(RuntimeError, match="auth failed"):
            ref_main._safe_clone_source_repo(handler, "https://x", tmp_path)


# ---------------------------------------------------------------------------
# _load_export_articles
# ---------------------------------------------------------------------------


class TestLoadExportArticles:
    def _write(self, tmp_path, payload, name="export.json"):
        p = tmp_path / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def _db(self, **kwargs):
        db = MagicMock()
        db.is_article_in_flight_or_done.return_value = kwargs.get("in_flight", False)
        return db

    def test_unreadable_export_returns_empty(self, tmp_path):
        assert (
            ref_main._load_export_articles(tmp_path / "missing.json", MagicMock(), None)
            == []
        )

    def test_legacy_list_payload(self, tmp_path):
        p = self._write(tmp_path, [_valid_article(1)])
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1

    def test_unexpected_format_returns_empty(self, tmp_path):
        p = self._write(tmp_path, {"articles": "nope"})
        assert ref_main._load_export_articles(p, MagicMock(), None) == []

    def test_invalid_schema_version_treated_legacy(self, tmp_path):
        p = self._write(
            tmp_path, {"schema_version": "abc", "articles": [_valid_article(1)]}
        )
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1

    def test_missing_schema_version_assumed_legacy(self, tmp_path):
        p = self._write(tmp_path, {"contract": "x.v2", "articles": [_valid_article(1)]})
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1

    def test_article_skipped_when_process_id_mismatch(self, tmp_path):
        p = self._write(tmp_path, {"articles": [_valid_article(1)]})
        assert ref_main._load_export_articles(p, self._db(), process_id="999") == []

    def test_invalid_payload_article_skipped(self, tmp_path):
        bad = _valid_article(1)
        bad["source_name"] = "No Such Source 99"
        bad.pop("source_id")
        p = self._write(tmp_path, {"articles": [bad]})
        assert ref_main._load_export_articles(p, self._db(), None) == []

    def test_in_flight_or_done_skips(self, tmp_path):
        p = self._write(tmp_path, {"articles": [_valid_article(1)]})
        articles = ref_main._load_export_articles(p, self._db(in_flight=True), None)
        assert articles == []

    def test_non_numeric_id_passes(self, tmp_path):
        art = _valid_article(1)
        art["id"] = "legacy-title-id"
        p = self._write(tmp_path, {"articles": [art]})
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1

    def test_ambiguous_source_names_disabled(self, tmp_path, monkeypatch):
        sources = {
            "s1": {"name": "Duplicate"},
            "s2": {"name": "Duplicate"},
            "s3": {"name": ""},
            "s4": {"name": "Unique"},
        }
        monkeypatch.setattr("news_collector.config.sources.ALL_SOURCES", sources)
        art = _valid_article(1)
        art["source_id"] = "s4"
        p = self._write(tmp_path, {"articles": [art]})
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1

    def test_source_name_fallback_resolves(self, tmp_path, monkeypatch):
        sources = {
            "known_id": {"name": "Known Source"},
        }
        monkeypatch.setattr("news_collector.config.sources.ALL_SOURCES", sources)
        art = _valid_article(1)
        art.pop("source_id")
        art["source_name"] = "known source"
        p = self._write(tmp_path, {"articles": [art]})
        articles = ref_main._load_export_articles(p, self._db(), None)
        assert len(articles) == 1
        assert articles[0]["source_id"] == "known_id"


# ---------------------------------------------------------------------------
# _select_export_articles
# ---------------------------------------------------------------------------


class TestSelectExportArticles:
    def _articles(self, n: int = 1) -> list:
        return [_valid_article(i) for i in range(1, n + 1)]

    def test_preferred_export_wins(self, tmp_path, monkeypatch):
        preferred = tmp_path / "preferred.json"
        preferred.touch()
        monkeypatch.setattr(
            ref_main, "_load_export_articles", lambda *a, **k: self._articles(1)
        )
        articles, selected = ref_main._select_export_articles(
            tmp_path / "cloud.json",
            tmp_path / "sibling.json",
            MagicMock(),
            None,
            preferred_path=preferred,
        )
        assert selected == preferred
        assert len(articles) == 1

    def test_preferred_empty_falls_to_cloud(self, tmp_path, monkeypatch):
        preferred = tmp_path / "preferred.json"
        preferred.touch()
        cloud = tmp_path / "cloud.json"
        cloud.touch()
        calls = {"n": 0}

        def _load(*a, **k):
            calls["n"] += 1
            return self._articles(1) if calls["n"] == 2 else []

        monkeypatch.setattr(ref_main, "_load_export_articles", _load)
        articles, selected = ref_main._select_export_articles(
            cloud,
            tmp_path / "sibling.json",
            MagicMock(),
            None,
            preferred_path=preferred,
        )
        assert selected == cloud
        assert len(articles) == 1

    def test_preferred_missing_falls_to_cloud(self, tmp_path, monkeypatch):
        cloud = tmp_path / "cloud.json"
        cloud.touch()
        monkeypatch.setattr(
            ref_main, "_load_export_articles", lambda *a, **k: self._articles(1)
        )
        articles, selected = ref_main._select_export_articles(
            cloud,
            tmp_path / "sibling.json",
            MagicMock(),
            None,
            preferred_path=tmp_path / "missing.json",
        )
        assert selected == cloud

    def test_cloud_empty_falls_to_sibling(self, tmp_path, monkeypatch):
        cloud = tmp_path / "cloud.json"
        cloud.touch()
        sibling = tmp_path / "sibling.json"
        sibling.touch()
        calls = {"n": 0}

        def _load(*a, **k):
            calls["n"] += 1
            return self._articles(1) if calls["n"] == 2 else []

        monkeypatch.setattr(ref_main, "_load_export_articles", _load)
        articles, selected = ref_main._select_export_articles(
            cloud, sibling, MagicMock(), None
        )
        assert selected == sibling
        assert len(articles) == 1

    def test_no_exports_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            ref_main, "_load_export_articles", lambda *a, **k: self._articles(1)
        )
        articles, selected = ref_main._select_export_articles(
            tmp_path / "missing1.json", tmp_path / "missing2.json", MagicMock(), None
        )
        assert articles == []
        assert selected is None


# ---------------------------------------------------------------------------
# run_collector_script
# ---------------------------------------------------------------------------


class _FakeSystem:
    def __init__(self, initialize=True, run_error=None):
        self._initialize = initialize
        self._run_error = run_error
        self.shutdown_called = False
        self.exports = []
        self.config_override = None

    def initialize(self):
        return self._initialize

    async def run_collection_cycle(self, dry_run=None):
        if self._run_error:
            raise self._run_error

    def export_latest_articles(self, file_path=None, limit=None):
        self.exports.append((file_path, limit))

    async def shutdown(self):
        self.shutdown_called = True


class TestRunCollectorScript:
    def test_success_and_export(self, monkeypatch):
        system = _FakeSystem()
        monkeypatch.setattr(
            ref_main, "create_system", lambda config_override=None: system
        )
        ref_main.run_collector_script(Path("/tmp/source"), fast_mode=False)
        assert system.exports
        assert system.shutdown_called

    def test_fast_mode_overrides_scoring(self, monkeypatch):
        captured = {}

        def _create(config_override=None):
            captured["config_override"] = config_override
            return _FakeSystem()

        monkeypatch.setattr(ref_main, "create_system", _create)
        ref_main.run_collector_script(Path("/tmp/source"), fast_mode=True)
        assert (
            captured["config_override"]["scoring_weights"]["cognitive_engagement"]
            == 0.0
        )

    def test_dry_run_skips_export(self, monkeypatch):
        system = _FakeSystem()
        monkeypatch.setattr(
            ref_main, "create_system", lambda config_override=None: system
        )
        ref_main.run_collector_script(Path("/tmp/source"), dry_run=True)
        assert system.exports == []
        assert system.shutdown_called

    def test_initialize_failure_returns(self, monkeypatch):
        system = _FakeSystem(initialize=False)
        monkeypatch.setattr(
            ref_main, "create_system", lambda config_override=None: system
        )
        ref_main.run_collector_script(Path("/tmp/source"))
        assert system.shutdown_called is False

    def test_runtime_error_loop_conflict(self, monkeypatch):
        system = _FakeSystem(run_error=RuntimeError("event loop is already running"))
        monkeypatch.setattr(
            ref_main, "create_system", lambda config_override=None: system
        )
        captured = []

        def _err(msg, *a, **k):
            captured.append(str(msg))

        monkeypatch.setattr("apps.refinery.main.logger.error", _err)
        ref_main.run_collector_script(Path("/tmp/source"))
        assert any("Async loop conflict" in m for m in captured)

    def test_generic_exception_logged(self, monkeypatch):
        def _create(config_override=None):
            raise ValueError("collector exploded")

        monkeypatch.setattr(ref_main, "create_system", _create)
        ref_main.run_collector_script(Path("/tmp/source"))


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMainPaths:
    def test_config_error_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            ref_main,
            "load_config",
            lambda: (_ for _ in ()).throw(ValueError("bad toml")),
        )
        result = ref_main.main()
        assert result["status"] == "error"
        assert "bad toml" in result["message"]

    def test_success_via_preferred_export(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        export = tmp_path / "export.json"
        export.write_text(
            json.dumps({"articles": [_valid_article(1)]}), encoding="utf-8"
        )
        deps["engine"].process_articles.return_value = {
            "processed_count": 1,
            "errors": [],
        }
        monkeypatch.setattr(
            ref_main,
            "_select_export_articles",
            lambda *a, **k: ([_valid_article(1)], export),
        )
        target = tmp_path / "target"
        target.mkdir()
        monkeypatch.setattr(ref_main.git, "Repo", lambda _path: _DummyRepo())
        result = ref_main.main(export_path=str(export), process_new_content=True)
        assert result["status"] == "success"
        assert result["processed_count"] == 1

    def test_manual_ingest_failure(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)

        class _FakeIngest:
            def __init__(self, *a, **k):
                pass

            def ingest(self, url):
                return {
                    "status": "error",
                    "message": "Fetch failed for url",
                    "processed_count": 0,
                    "error_code": "fetch_failed",
                }

        monkeypatch.setattr(ref_main, "ManualUrlIngestService", _FakeIngest)
        result = ref_main.main(article_url="https://example.org/broken")
        assert result["status"] == "error"
        assert result["error_code"] == "fetch_failed"

    def test_clone_source_failure(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        deps["git_handler"].clone_repo.side_effect = RuntimeError("source clone failed")
        result = ref_main.main()
        assert result["status"] == "error"
        assert "Failed to clone source repo" in result["message"]

    def test_fetch_only(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        result = ref_main.main(fetch_only=True)
        assert result["status"] == "success"

    def test_dev_mode_injects_mock_when_dir_empty(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        deps["db"].is_processed.return_value = False

        result = ref_main.main(dev=True, process_new_content=False)
        assert result["status"] == "success"
        assert (data_dir / "mock_article.md").exists()

    def test_file_scan_ignores_and_skips(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "README.md").write_text("ignored", encoding="utf-8")
        (data_dir / "test").mkdir()
        (data_dir / "test" / "sub.md").write_text("sub", encoding="utf-8")
        (data_dir / "ready.md").write_text("ready", encoding="utf-8")
        (data_dir / "broken.md").mkdir()
        (data_dir / "normal.md").write_text("normal", encoding="utf-8")
        deps["db"].is_processed.side_effect = lambda name: name == "ready.md"

        result = ref_main.main(process_new_content=False)
        assert result["status"] == "success"
        assert (data_dir / "mock_article.md").exists() is False

    def test_no_articles_noop(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        result = ref_main.main()
        assert result["status"] == "noop"

    def test_noop_includes_export_path(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        export = tmp_path / "export.json"
        export.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            ref_main, "_select_export_articles", lambda *a, **k: ([], export)
        )
        result = ref_main.main(export_path=str(export))
        assert result["status"] == "noop"
        assert "Export revisado" in result["message"]

    def test_bulk_limit_and_auto_process_disabled(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        for i in range(8):
            (data_dir / f"a{i}.md").write_text(f"content {i}", encoding="utf-8")
        deps["db"].is_processed.return_value = False
        result = ref_main.main()
        assert result["status"] == "success"
        assert "Ready for review" in result["message"]

    def test_process_id_file_fallback_and_success(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "wanted.md").write_text("wanted body", encoding="utf-8")
        (data_dir / "other.md").write_text("other body", encoding="utf-8")
        deps["db"].is_processed.return_value = False
        target = tmp_path / "target"
        target.mkdir()
        monkeypatch.setattr(ref_main.git, "Repo", lambda _path: _DummyRepo())
        monkeypatch.setattr(
            ref_main, "_safe_clone_source_repo", lambda *_a, **_k: source
        )

        result = ref_main.main(process_id="wanted")
        assert result["status"] == "success"
        assert result["processed_count"] == 1

    def test_engine_failure(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "x.md").write_text("x", encoding="utf-8")
        deps["db"].is_processed.return_value = False
        deps["engine"].process_articles.side_effect = RuntimeError("engine crashed")
        target = tmp_path / "target"
        target.mkdir()
        monkeypatch.setattr(ref_main.git, "Repo", lambda _path: _DummyRepo())
        monkeypatch.setattr(
            ref_main, "_safe_clone_source_repo", lambda *_a, **_k: source
        )

        result = ref_main.main(process_id="x")
        assert result["status"] == "error"
        assert "Engine failed" in result["message"]

    def test_keyboard_interrupt(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "x.md").write_text("x", encoding="utf-8")
        deps["db"].is_processed.return_value = False
        deps["engine"].process_articles.side_effect = KeyboardInterrupt()
        target = tmp_path / "target"
        target.mkdir()
        monkeypatch.setattr(ref_main.git, "Repo", lambda _path: _DummyRepo())
        monkeypatch.setattr(
            ref_main, "_safe_clone_source_repo", lambda *_a, **_k: source
        )

        result = ref_main.main(process_id="x")
        assert result["status"] == "cancelled"

    def test_target_clone_failure(self, tmp_path, monkeypatch):
        deps = _patch_main_deps(monkeypatch, tmp_path)
        source = tmp_path / "source"
        data_dir = source / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "x.md").write_text("x", encoding="utf-8")
        deps["db"].is_processed.return_value = False
        monkeypatch.setattr(
            ref_main.git,
            "Repo",
            lambda _path: (_ for _ in ()).throw(RuntimeError("git corrupt")),
        )
        monkeypatch.setattr(
            ref_main, "_safe_clone_source_repo", lambda *_a, **_k: source
        )
        result = ref_main.main(process_id="x")
        assert result["status"] == "error"
        assert "Critical Git Error" in result["message"]


# ---------------------------------------------------------------------------
# _normalize_delete_target / delete_article
# ---------------------------------------------------------------------------


class TestNormalizeDeleteTarget:
    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            ref_main._normalize_delete_target("  ")

    def test_non_str_non_dict_raises(self):
        with pytest.raises(ValueError, match="string or a dict"):
            ref_main._normalize_delete_target(123)

    def test_dict_without_keys_raises(self):
        with pytest.raises(ValueError, match="refinery_id"):
            ref_main._normalize_delete_target({"nope": "x"})

    def test_string_target(self):
        assert ref_main._normalize_delete_target(" abc ") == {"refinery_id": "abc"}

    def test_dict_target_with_path_sanitized(self):
        assert ref_main._normalize_delete_target(
            {"file_name": "posts/../../evil.md"}
        ) == {"file_name": "evil.md"}


class TestDeleteArticle:
    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            github=SimpleNamespace(
                token="token",
                target_repo_url="https://github.com/org/target",
            )
        )

    def test_not_found_returns_error(self, tmp_path, monkeypatch):
        target = tmp_path / "target"
        (target / "src/content/posts").mkdir(parents=True)
        monkeypatch.setattr(ref_main, "load_config", lambda: self._config())
        handler = MagicMock()
        monkeypatch.setattr(ref_main, "GitHubPublisher", lambda token: handler)
        monkeypatch.setattr(ref_main.git, "Repo", lambda _path: _DummyRepo())
        monkeypatch.setattr(ref_main, "TARGET_DIR", target)
        result = ref_main.delete_article({"refinery_id": "missing"})
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_exception_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ref_main, "load_config", lambda: self._config())
        handler = MagicMock()
        handler.clone_repo.side_effect = RuntimeError("clone boom")
        monkeypatch.setattr(ref_main, "GitHubPublisher", lambda token: handler)
        monkeypatch.setattr(ref_main, "TARGET_DIR", tmp_path / "target")
        result = ref_main.delete_article({"refinery_id": "x"})
        assert result["status"] == "error"
        assert "clone boom" in result["message"]
