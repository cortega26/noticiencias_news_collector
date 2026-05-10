"""Targeted tests for uncovered branches in bootstrap, reporting, and source_health."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from news_collector.system import bootstrap
from news_collector.system.reporting import (
    export_latest_articles,
    get_system_statistics,
    get_top_articles,
)
from news_collector.system.source_health import (
    _normalize_last_run,
    _to_float,
    _to_int,
    build_source_health_record,
    classify_failure_taxonomy,
    classify_operational_state,
)


# ---------------------------------------------------------------------------
# bootstrap coverage
# ---------------------------------------------------------------------------

class TestBootstrapUtilities:
    """Cover simple utility functions in bootstrap.py."""

    def test_is_smoke_mode_enabled_false(self):
        assert bootstrap._is_smoke_mode_enabled() is False

    def test_is_smoke_mode_enabled_true(self, monkeypatch):
        monkeypatch.setenv("NOTICIENCIAS_SMOKE", "true")
        assert bootstrap._is_smoke_mode_enabled() is True

    def test_resolve_module_logger_none(self):
        assert bootstrap._resolve_module_logger(None) is None

    def test_resolve_module_logger_with_factory(self):
        factory = MagicMock()
        result = bootstrap._resolve_module_logger(factory)
        assert result is not None
        factory.create_module_logger.assert_called_once_with("system")

    def test_resolve_module_logger_plain(self):
        logger = object()
        result = bootstrap._resolve_module_logger(logger)
        assert result is logger

    def test_validate_system_config_override(self):
        logger = MagicMock()
        # No error expected — validate_config / validate_sources are no-ops under patches
        with (
            patch("news_collector.system.bootstrap.validate_config"),
            patch("news_collector.system.bootstrap.validate_sources"),
        ):
            bootstrap.validate_system_config({"scoring_mode": "strict"}, logger)
        assert logger.create_module_logger.called

    def test_build_database_with_logger(self):
        logger = MagicMock()
        with patch("news_collector.system.bootstrap.get_database_manager") as mock_db:
            db = MagicMock()
            mock_db.return_value = db
            result = bootstrap.build_database(logger)
        assert result is db
        assert logger.create_module_logger.called

    def test_build_collectors_with_logger(self):
        logger = MagicMock()
        health = MagicMock()
        with patch(
            "news_collector.collectors.dispatcher.CollectorDispatcher"
        ) as mock_cls:
            dispatcher = MagicMock()
            mock_cls.return_value = dispatcher
            result = bootstrap.build_collectors(logger, health)
        assert result is dispatcher
        assert logger.create_module_logger.called

    def test_build_validator_with_logger(self):
        logger = MagicMock()
        with patch("news_collector.system.bootstrap.ContentValidator") as mock_val:
            validator = MagicMock()
            mock_val.return_value = validator
            result = bootstrap.build_validator(logger)
        assert result is validator
        assert logger.create_module_logger.called

    def test_build_scorer_with_logger(self):
        logger = MagicMock()
        with patch("news_collector.scoring.create_scorer") as mock_scr:
            scorer = MagicMock()
            mock_scr.return_value = scorer
            result = bootstrap.build_scorer({"scoring_weights": {}}, logger)
        assert result is scorer
        assert logger.create_module_logger.called

    def test_bootstrap_system(self):
        """bootstrap_system is a thin wrapper — verify it calls preflight."""
        with patch(
            "news_collector.system.bootstrap._verify_llm_health"
        ) as mock_verify:
            warnings = bootstrap.bootstrap_system()
        assert warnings == []
        assert mock_verify.called

    def test_preflight_llm_provider_returns_warnings(self):
        """preflight should return the warnings list from _verify_llm_health."""
        with patch(
            "news_collector.system.bootstrap._verify_llm_health"
        ) as mock_verify:
            mock_verify.side_effect = None  # appends to warnings list
            warnings = bootstrap.preflight_llm_provider()
        assert warnings == []
        assert mock_verify.called


class TestVerifyLlmHealth:
    """Cover branches in _verify_llm_health."""

    def test_smoke_mode_disables_llm(self, monkeypatch):
        monkeypatch.setenv("NOTICIENCIAS_SMOKE", "true")
        with patch("news_collector.system.bootstrap._resolve_module_logger") as mock_res:
            bootstrap._verify_llm_health(MagicMock(), [])
        from news_collector.config import settings as config_settings
        assert config_settings.RUNTIME.llm_system_available is False
        mock_res.assert_called_once()

    def test_checker_none_returns_early(self):
        """If resolve_health_checker returns None, function returns."""
        with (
            patch("news_collector.system.bootstrap._resolve_module_logger"),
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=None,
            ),
        ):
            bootstrap._verify_llm_health(MagicMock(), [])

    def test_checker_success_no_warning(self):
        """Happy path: checker succeeds, no warning, no disable."""
        checker = MagicMock()
        result = MagicMock()
        result.warning = None
        result.disable_llm = False
        result.error = None
        checker.check.return_value = result
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger"),
            patch("news_collector.config.settings.RUNTIME") as mock_runtime,
        ):
            bootstrap._verify_llm_health(MagicMock(), [])
        assert mock_runtime.llm_system_available is True

    def test_checker_with_warning(self):
        """Checker returns a warning that gets appended."""
        checker = MagicMock()
        result = MagicMock()
        result.warning = "LLM is slow"
        result.disable_llm = False
        result.error = None
        checker.check.return_value = result
        warnings: list[str] = []
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger"),
        ):
            bootstrap._verify_llm_health(MagicMock(), warnings)
        assert "LLM is slow" in warnings

    def test_checker_disable_llm_no_error(self):
        """Checker says disable LLM but no strict mode — no raise."""
        checker = MagicMock()
        result = MagicMock()
        result.warning = None
        result.disable_llm = True
        result.error = None
        checker.check.return_value = result
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger"),
            patch("news_collector.config.settings.RUNTIME") as mock_runtime,
        ):
            bootstrap._verify_llm_health(MagicMock(), [])
        assert mock_runtime.llm_system_available is False

    def test_checker_exception_graceful(self):
        """Non-RuntimeError exception — log warning and continue."""
        checker = MagicMock()
        checker.check.side_effect = ValueError("timeout")
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger") as mock_res,
            patch("news_collector.config.settings.RUNTIME") as mock_runtime,
        ):
            logger = MagicMock()
            health_logger = MagicMock()
            mock_res.return_value = health_logger
            bootstrap._verify_llm_health(logger, [])
        assert mock_runtime.llm_system_available is False

    def test_checker_exception_strict_mode_raises(self):
        """Strict mode + exception — raises RuntimeError."""
        import os
        with patch.dict(os.environ, {"NOTICIENCIAS_LLM_STRICT": "true"}, clear=False):
            # Re-import or use is_strict_mode_enabled directly
            checker = MagicMock()
            checker.check.side_effect = ValueError("connection failed")
            with (
                patch(
                    "news_collector.infrastructure.llm.health.resolve_health_checker",
                    return_value=checker,
                ),
                patch("news_collector.system.bootstrap._resolve_module_logger"),
                patch(
                    "news_collector.infrastructure.llm.model_registry.is_strict_mode_enabled",
                    return_value=True,
                ),
            ):
                with pytest.raises(RuntimeError, match="connection failed"):
                    bootstrap._verify_llm_health(MagicMock(), [])

    def test_checker_raises_runtime_error(self):
        """RuntimeError from checker.check is re-raised."""
        checker = MagicMock()
        checker.check.side_effect = RuntimeError("checker internal")
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger"),
        ):
            with pytest.raises(RuntimeError, match="checker internal"):
                bootstrap._verify_llm_health(MagicMock(), [])

    def test_checker_disable_with_strict_raises(self):
        """disable_llm + error + strict mode raises RuntimeError."""
        checker = MagicMock()
        result = MagicMock()
        result.warning = None
        result.disable_llm = True
        result.error = "model overloaded"
        checker.check.return_value = result
        with (
            patch(
                "news_collector.infrastructure.llm.health.resolve_health_checker",
                return_value=checker,
            ),
            patch("news_collector.system.bootstrap._resolve_module_logger"),
            patch(
                "news_collector.infrastructure.llm.model_registry.is_strict_mode_enabled",
                return_value=True,
            ),
        ):
            with pytest.raises(RuntimeError, match="model overloaded"):
                bootstrap._verify_llm_health(MagicMock(), [])


# ---------------------------------------------------------------------------
# reporting coverage
# ---------------------------------------------------------------------------

class TestReportingCoverage:
    """Cover error branches in news_collector.system.reporting."""

    def test_get_top_articles_uninitialized(self):
        system = SimpleNamespace(is_initialized=False)
        with pytest.raises(RuntimeError, match="no inicializado"):
            get_top_articles(system)

    def test_export_latest_articles_uninitialized(self):
        system = SimpleNamespace(is_initialized=False)
        with pytest.raises(RuntimeError, match="no inicializado"):
            export_latest_articles(system)

    def test_get_system_statistics_uninitialized(self):
        system = SimpleNamespace(is_initialized=False)
        with pytest.raises(RuntimeError, match="no inicializado"):
            get_system_statistics(system)

    def test_export_latest_articles_with_path(self, tmp_path):
        """Cover the file-writing path in export_latest_articles."""
        system = SimpleNamespace(
            is_initialized=True,
            start_time=datetime.now(timezone.utc),
            system_id="test",
            db_manager=MagicMock(),
            logger=MagicMock(),
        )
        system.db_manager.get_articles_by_score.return_value = []
        export_path = tmp_path / "exports" / "test.json"
        with patch("news_collector.contracts.adapters.adapt_article_to_export"):
            result = export_latest_articles(system, str(export_path), limit=5)
        assert export_path.exists()
        assert result["article_count"] == 0

    def test_get_top_articles_db_error(self):
        """Exception handler in get_top_articles."""
        system = SimpleNamespace(
            is_initialized=True,
            db_manager=MagicMock(),
            logger=MagicMock(),
        )
        system.db_manager.get_articles_by_score.side_effect = ValueError("db error")
        with pytest.raises(ValueError, match="db error"):
            get_top_articles(system)

    def test_get_system_statistics_db_error(self):
        """Exception handler in get_system_statistics."""
        system = SimpleNamespace(
            is_initialized=True,
            start_time=datetime.now(timezone.utc),
            system_id="test",
            db_manager=MagicMock(),
            logger=MagicMock(),
        )
        system.db_manager.get_health_status.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            get_system_statistics(system)


# ---------------------------------------------------------------------------
# source_health coverage
# ---------------------------------------------------------------------------

class TestSourceHealthCoverage:
    """Cover utility and branch gaps in source_health.py."""

    def test_to_float_type_error(self):
        assert _to_float("not-a-number") == 0.0

    def test_to_int_type_error(self):
        assert _to_int("not-an-int") == 0

    def test_normalize_last_run_str(self):
        result = _normalize_last_run("2026-05-10T12:00:00+00:00")
        assert result == "2026-05-10T12:00:00+00:00"

    def test_normalize_last_run_none(self):
        assert _normalize_last_run(None) is None

    def test_classify_failure_articles_saved_no_error(self):
        """articles_saved > 0 and no error_blob → None."""
        assert classify_failure_taxonomy(
            feed_ok=True,
            pipeline_ok=True,
            articles_saved=3,
            last_error_message=None,
        ) is None

    def test_classify_failure_publication_contract(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="permalink validation failed",
        )
        assert result == "publication_contract_failure"

    def test_classify_failure_editorial(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="relevance score too low",
        )
        assert result == "editorial_relevance_rejection"

    def test_classify_failure_anti_bot(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="cloudflare challenge",
        )
        assert result == "anti_bot_block"

    def test_classify_failure_js_render(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="javascript render timeout",
        )
        assert result == "js_render_required"

    def test_classify_failure_http_blocked(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="403 forbidden",
        )
        assert result == "article_fetch_blocked"

    def test_classify_failure_content_short(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="content_too_short",
        )
        assert result == "content_too_short"

    def test_classify_failure_extraction_parser(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="parse error at line 42",
        )
        assert result == "extraction_parser_mismatch"

    def test_classify_failure_feed_and_pipeline_down(self):
        result = classify_failure_taxonomy(
            feed_ok=False, pipeline_ok=False, articles_saved=0,
            last_error_message=None,
        )
        assert result == "feed_fetch_failure"

    def test_classify_failure_unknown(self):
        result = classify_failure_taxonomy(
            feed_ok=True, pipeline_ok=True, articles_saved=0,
            last_error_message="something unexpected happened",
        )
        assert result == "unknown_failure"

    def test_classify_operational_state_full_text_healthy(self):
        result = classify_operational_state(
            content_mode="full_text", articles_found=10, articles_saved=8, save_ratio=0.8
        )
        assert result == "healthy_full_text"

    def test_classify_operational_state_summary_healthy(self):
        result = classify_operational_state(
            content_mode="summary_only", articles_found=10, articles_saved=5, save_ratio=0.5
        )
        assert result == "healthy_summary_only"

    def test_classify_operational_state_partial(self):
        result = classify_operational_state(
            content_mode="summary_only", articles_found=10, articles_saved=1, save_ratio=0.1
        )
        assert result == "partial_yield_flaky"

    def test_classify_operational_state_failing(self):
        result = classify_operational_state(
            content_mode="full_text", articles_found=0, articles_saved=0, save_ratio=0.0
        )
        assert result == "failing_suppressed_candidate"

    def test_build_source_health_record_empty(self):
        """Cover edge inputs in build_source_health_record."""
        record = build_source_health_record(
            "test-source",
            source_config={"name": "Test", "language": "en"},
            observed={},
            metrics={},
            last_run=None,
        )
        assert record.source_id == "test-source"
        assert record.source_name == "Test"
        assert record.articles_found == 0
        assert record.articles_saved == 0
        assert record.save_ratio == 0.0
