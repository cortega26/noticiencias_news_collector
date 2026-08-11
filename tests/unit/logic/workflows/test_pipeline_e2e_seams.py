"""Unit tests for the deterministic E2E publication seams (plan 041).

The harness stubs the editor, git, and auditor so full-pipeline scenarios
run deterministically without LLM/network calls.  These tests pin the stub
contracts so the stubs cannot silently drift from the interfaces the
RefineryEngine calls.
"""

from __future__ import annotations

from news_collector.logic.workflows.pipeline_e2e import (
    LocalEditorialAuditor,
    LocalEditorialEditor,
    LocalPRGitHandler,
)


def test_local_editorial_auditor_declines_audits():
    auditor = LocalEditorialAuditor()
    assert auditor.should_run_fast({"id": "1"}, "content") is False
    assert auditor.get_cached_score("1") is None
    result = auditor.audit_article_sync(article_id="1", content="x")
    assert result["status"] == "audit_unavailable"


def test_local_editorial_auditor_accepts_positional_args():
    # audit_article_sync is submitted through executor.submit(..., article_id=...,
    # content=..., ...); ensure kwargs-only signatures are not assumed.
    auditor = LocalEditorialAuditor()
    result = auditor.audit_article_sync("1", "content", "url")
    assert result["status"] == "audit_unavailable"


def test_local_pr_git_handler_returns_deterministic_pr_url():
    handler = LocalPRGitHandler()
    url = handler.create_pull_request(
        repo_url="https://example.test/r",
        branch_name="content/update-x",
        title="t",
        body="b",
    )
    assert url == "https://example.test/pr/content/update-x"


def test_local_editorial_editor_produces_frontmatter_with_refinery_id():
    editor = LocalEditorialEditor()
    content = editor.process_article(
        {"title": "Un articulo de prueba", "url": "https://example.test/a"},
        override_date="2026-08-10",
        explicit_article_id="42",
    )
    assert "refinery_id: '42'" in content
    assert "---" in content
