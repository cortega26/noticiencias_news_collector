"""Unit tests for frontend publication validation helpers and failure branches."""

import json
import subprocess
from datetime import date
from pathlib import Path

from news_collector.logic.workflows.frontend_publication_validation import (
    _classify_failure,
    _cleanup_fixture,
    _load_manifest,
    _record_check,
    _stage_fixture,
    build_fixture_post,
    render_fixture_markdown,
    run_frontend_publication_validation,
)


def test_render_fixture_markdown_omits_optional_fields() -> None:
    post = build_fixture_post()
    post.permalink = None
    post.source_url = None
    rendered = render_fixture_markdown(post)
    assert "permalink:" not in rendered
    assert "source_url:" not in rendered


def test_classify_failure_permalink_collision() -> None:
    assert _classify_failure("lint", "duplicate permalink detected") == (
        "permalink_collision"
    )


def test_classify_failure_taxonomy_violations() -> None:
    assert _classify_failure("lint", "[check:tags] tag violations") == (
        "taxonomy_contract_violation"
    )
    assert _classify_failure("lint", "tag contains disallowed value") == (
        "taxonomy_contract_violation"
    )
    assert _classify_failure("lint", "taxonomy mismatch") == (
        "taxonomy_contract_violation"
    )


def test_classify_failure_sidecar_variants() -> None:
    assert _classify_failure("lint", "refinery_manifest missing") == (
        "sidecar_missing_or_malformed"
    )
    assert _classify_failure("lint", "stale manifest entry") == (
        "sidecar_missing_or_malformed"
    )
    assert _classify_failure("lint", "escapes posts directory") == (
        "sidecar_missing_or_malformed"
    )
    assert _classify_failure("lint", "must map to a non-empty filename") == (
        "sidecar_missing_or_malformed"
    )


def test_classify_failure_check_name_branches() -> None:
    assert _classify_failure("build", "output") == "frontend_build_failure"
    assert _classify_failure("test_dist", "output") == "frontend_dist_failure"
    assert _classify_failure("test_audit", "output") == "frontend_audit_failure"
    assert _classify_failure("other", "output") == "schema_mismatch"


def test_load_manifest_missing_and_malformed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    assert _load_manifest(missing) == ({}, None)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    try:
        _load_manifest(malformed)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "JSON object" in str(exc)

    non_strings = tmp_path / "mixed.json"
    non_strings.write_text(json.dumps({"a": "b", "num": 1}), encoding="utf-8")
    normalized, original = _load_manifest(non_strings)
    assert normalized == {"a": "b"}
    assert original is not None


def test_cleanup_fixture_without_original_manifest(tmp_path: Path) -> None:
    posts_dir = tmp_path / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True)
    post_path = posts_dir / "_smoke-test.md"
    manifest_path = posts_dir / "refinery_manifest.json"
    post_path.write_text("fixture", encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")

    staged = {
        "post_path": str(post_path),
        "manifest_path": str(manifest_path),
        "original_manifest_text": None,
    }
    _cleanup_fixture(tmp_path, staged)
    assert not post_path.exists()
    assert not manifest_path.exists()


def test_stage_fixture_writes_post_and_manifest(tmp_path: Path) -> None:
    staged = _stage_fixture(tmp_path)
    post_path = Path(staged["post_path"])
    manifest_path = Path(staged["manifest_path"])
    assert post_path.exists()
    assert "title: 'Publication Smoke Test Article'" in post_path.read_text(
        encoding="utf-8"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["smoke-test-ci-fixture"] == "_smoke-test.md"


def test_stage_fixture_failure_writes_summary(tmp_path: Path) -> None:
    posts_dir = tmp_path / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True)
    (posts_dir / "refinery_manifest.json").write_text("[]", encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    summary = run_frontend_publication_validation(
        tmp_path,
        summary_output_path=summary_path,
        command_runner=None,
    )
    assert summary.success is False
    assert summary.overall_failure_class == "sidecar_missing_or_malformed"
    assert summary.checks[0].name == "stage_fixture"
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["success"] is False


def test_record_check_stdout_stderr_and_failure(tmp_path: Path) -> None:
    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="out", stderr="err")

    result = _record_check("lint", ["npm", "run", "lint"], tmp_path, runner)
    assert result.success is False
    assert result.stdout == "out"
    assert result.stderr == "err"
    assert result.returncode == 1
    assert result.failure_class is not None


def test_run_current_state_without_post_path(tmp_path: Path) -> None:
    posts_dir = tmp_path / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True)

    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    summary = run_frontend_publication_validation(
        tmp_path,
        command_runner=runner,
        stage_fixture=False,
        install_dependencies=False,
    )
    assert summary.success is True
    assert summary.artifacts["validation_mode"] == "current_state"
    assert [check.name for check in summary.checks] == [
        "publish_image_derivatives",
        "format_repo",
        "lint",
        "validate_content",
        "build",
        "test_dist",
        "test_audit",
    ]
