"""Unit tests for the deterministic E2E publication seams (plan 041).

The harness stubs the editor, git, and auditor so full-pipeline scenarios
run deterministically without LLM/network calls.  These tests pin the stub
contracts so the stubs cannot silently drift from the interfaces the
RefineryEngine calls.
"""

from __future__ import annotations

from pathlib import Path

from news_collector.logic.workflows.pipeline_e2e import (
    LocalEditorialAuditor,
    LocalEditorialEditor,
    LocalPRGitHandler,
    _article_to_dicts,
    _parse_published,
    _relative_fixture_dates,
    _write_frontend_fixture_repo,
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


def test_write_frontend_fixture_repo_creates_standalone_checkout(tmp_path: Path):
    """The fixture-only frontend checkout (used when no real repo is
    present) must produce a valid git repo with package.json, the check
    script, and the manifest."""
    scenario = {
        "frontend_fixture": {
            "preexisting_posts": [
                {
                    "filename": "2024-01-01-old.md",
                    "refinery_id": "7",
                    "content": "---\ntitle: old\n---\nbody",
                }
            ]
        }
    }
    target = tmp_path / "fixture_repo"
    result = _write_frontend_fixture_repo(target, scenario)

    assert result == target
    assert (target / "package.json").exists()
    assert (target / "scripts" / "check.js").exists()
    assert (target / "node_modules").is_dir()
    assert (target / "src" / "content" / "posts" / "2024-01-01-old.md").exists()
    assert (target / ".git").exists()

    import json

    manifest = json.loads(
        (target / "src" / "content" / "posts" / "refinery_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest == {"7": "2024-01-01-old.md"}


def test_parse_published_handles_z_suffix_and_naive():
    aware = _parse_published("2026-05-07T12:00:00Z")
    assert aware is not None and aware.tzinfo is not None
    naive = _parse_published("2026-05-07T12:00:00")
    assert naive is not None and naive.tzinfo is not None
    assert _parse_published("not-a-date") is None


def test_relative_fixture_dates_shifts_into_recency_window():
    fixture = {
        "replay_events": [
            {
                "articles": [
                    {"published": "2024-01-01T00:00:00Z"},
                    {"published": "2024-01-02T00:00:00Z"},
                ]
            }
        ]
    }
    shifted = _relative_fixture_dates(fixture)
    articles = shifted["replay_events"][0]["articles"]
    assert articles[1]["published"].endswith("+00:00")
    from datetime import datetime, timezone

    first = datetime.fromisoformat(articles[0]["published"])
    second = datetime.fromisoformat(articles[1]["published"])
    assert (second - first).total_seconds() == 24 * 3600  # relative gap preserved


def test_relative_fixture_dates_tolerates_missing_or_bad_dates():
    assert _relative_fixture_dates({"replay_events": []}) == {"replay_events": []}
    assert _relative_fixture_dates({"replay_events": "not-a-list"}) == {
        "replay_events": "not-a-list"
    }
    fixture = {"replay_events": [{"articles": [{"published": None}]}]}
    assert _relative_fixture_dates(fixture) == fixture


def test_article_to_dicts_handles_orm_objects_and_plain_dicts():
    class WithAttrs:
        def to_dict(self):
            return {"id": 1, "title": "x"}

        article_metadata = {"m": 1}
        processing_status = "pending"
        error_message = None
        content = "body"

    class MissingAttrs:
        def to_dict(self):
            return {"id": 2}

    result = _article_to_dicts([WithAttrs(), MissingAttrs(), {"id": 3}])
    assert result[0]["article_metadata"] == {"m": 1}
    assert result[0]["content"] == "body"
    assert result[1] == {"id": 2}
    assert result[2] == {"id": 3}
