from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from news_collector.logic.workflows.refinery_engine import RefineryEngine


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            result = fn(*args, **kwargs)
            future.set_result(result)
        except Exception as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        return future


def test_pr_created_state_is_persisted_when_optional_audit_times_out(tmp_path: Path):
    mock_db = MagicMock()
    mock_db.get_canonical_slug.return_value = None
    mock_db.get_publishing_state.return_value = None
    mock_db.mark_article_published.return_value = True
    mock_db.update_article_audit_status.return_value = True

    mock_git = MagicMock()
    mock_git.create_branch.return_value = "content/update/2026-03-02-article-1087"
    mock_git.create_pull_request.return_value = "https://example.test/pr/1087"

    mock_editor = MagicMock()
    mock_editor.process_article.return_value = (
        '---\nslug: article-1087\nrefinery_id: "1087"\n---\n\nContenido auditado.'
    )

    config = SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled", editorial_mode="standard"
        ),
        github=SimpleNamespace(target_repo_url="https://github.com/org/repo"),
        paths=SimpleNamespace(data_dir=str(tmp_path / "data")),
    )
    engine = RefineryEngine(mock_db, mock_git, mock_editor, config)
    engine.executor = _ImmediateExecutor()

    engine.auditor = MagicMock()
    engine.auditor.get_cached_score.return_value = {
        "epistemic_rigor_score": 10.0,
        "has_proper_caveats": True,
    }
    engine.auditor.should_run_fast.return_value = True
    engine.auditor.audit_article_sync.return_value = {
        "status": "audit_failed",
        "reason": "timeout after 3 attempts (timeout=15s)",
        "attempts": 3,
        "timeout_seconds": 15,
        "model": "llama3.3:latest",
        "endpoint": "http://localhost:11434/api/generate",
    }
    engine.policy.auditor_threshold = 0.0
    engine.policy.require_caveats = False
    engine._download_image = MagicMock(
        return_value="~/assets/images/article-1087.png"
    )

    article = {
        "id": 1087,
        "title": "Audit timeout should not fail publish",
        "url": "https://example.com/article-1087",
        "summary": "Valid summary for audit timeout staging test.",
        "content": "Valid content " * 200,
        "image_url": "https://example.com/article-1087.png",
        "source_id": "test-source",
        "source_name": "Test Source",
        "category": "science",
        "source_metadata": {},
        "published_date": datetime.now(timezone.utc).isoformat(),
    }

    result = engine.process_single_article(article, MagicMock(), tmp_path / "target")

    assert result is True
    mock_db.mark_article_published.assert_called_once_with(
        1087, "https://example.test/pr/1087"
    )

    audit_states = [
        call.args[1] for call in mock_db.update_article_audit_status.call_args_list
    ]
    assert "audit_pending" in audit_states
    assert "audit_failed" in audit_states
