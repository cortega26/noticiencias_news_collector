import json
import subprocess
from pathlib import Path

from news_collector.logic.workflows.frontend_publication_validation import (
    FIXTURE_ARTICLE_ID,
    FIXTURE_POST_FILENAME,
    MANIFEST_FILENAME,
    run_frontend_publication_validation,
)


def _prepare_frontend_root(tmp_path: Path) -> Path:
    frontend_root = tmp_path / "frontend"
    posts_dir = frontend_root / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True)
    manifest_path = posts_dir / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps({"existing-article": "2026-01-01-existing.md"}, indent=2) + "\n",
        encoding="utf-8",
    )
    return frontend_root


def test_frontend_publication_validation_success_restores_workspace(tmp_path: Path):
    frontend_root = _prepare_frontend_root(tmp_path)
    posts_dir = frontend_root / "src" / "content" / "posts"
    manifest_path = posts_dir / MANIFEST_FILENAME
    original_manifest = manifest_path.read_text(encoding="utf-8")
    executed_commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        executed_commands.append(command)
        assert cwd == frontend_root
        fixture_path = posts_dir / FIXTURE_POST_FILENAME
        assert fixture_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest[FIXTURE_ARTICLE_ID] == FIXTURE_POST_FILENAME
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    summary_path = tmp_path / "summary.json"
    summary = run_frontend_publication_validation(
        frontend_root,
        summary_output_path=summary_path,
        command_runner=runner,
    )

    assert summary.success is True
    assert summary.overall_failure_class is None
    assert [check.name for check in summary.checks] == [
        "npm_ci",
        "lint",
        "validate_content",
        "build",
        "test_dist",
        "test_audit",
    ]
    assert executed_commands[0] == ["npm", "ci"]
    assert not (posts_dir / FIXTURE_POST_FILENAME).exists()
    assert manifest_path.read_text(encoding="utf-8") == original_manifest

    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["success"] is True
    assert persisted["artifacts"]["fixture_article_id"] == FIXTURE_ARTICLE_ID


def test_frontend_publication_validation_classifies_build_failures(tmp_path: Path):
    frontend_root = _prepare_frontend_root(tmp_path)

    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command == ["npm", "run", "build"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="build failed",
                stderr="route generation exploded",
            )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    summary = run_frontend_publication_validation(
        frontend_root,
        command_runner=runner,
    )

    assert summary.success is False
    assert summary.overall_failure_class == "frontend_build_failure"
    assert [check.name for check in summary.checks] == [
        "npm_ci",
        "lint",
        "validate_content",
        "build",
    ]
    assert not (
        frontend_root / "src" / "content" / "posts" / FIXTURE_POST_FILENAME
    ).exists()


def test_frontend_publication_validation_fails_on_malformed_manifest(tmp_path: Path):
    frontend_root = tmp_path / "frontend"
    posts_dir = frontend_root / "src" / "content" / "posts"
    posts_dir.mkdir(parents=True)
    (posts_dir / MANIFEST_FILENAME).write_text("[]", encoding="utf-8")

    summary = run_frontend_publication_validation(frontend_root)

    assert summary.success is False
    assert summary.overall_failure_class == "sidecar_missing_or_malformed"
    assert summary.checks[0].name == "stage_fixture"


def test_frontend_publication_validation_current_state_does_not_stage_fixture(
    tmp_path: Path,
):
    frontend_root = _prepare_frontend_root(tmp_path)
    posts_dir = frontend_root / "src" / "content" / "posts"
    post_path = posts_dir / "2026-01-01-real-post.md"
    post_path.write_text("---\ntitle: Real\n---\nBody", encoding="utf-8")
    executed_commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        executed_commands.append(command)
        assert cwd == frontend_root
        assert post_path.exists()
        assert not (posts_dir / FIXTURE_POST_FILENAME).exists()
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    summary = run_frontend_publication_validation(
        frontend_root,
        command_runner=runner,
        stage_fixture=False,
        post_path=post_path,
        install_dependencies=False,
    )

    assert summary.success is True
    assert [check.name for check in summary.checks] == [
        "lint",
        "validate_content",
        "build",
        "test_dist",
        "test_audit",
    ]
    assert summary.artifacts["validation_mode"] == "current_state"
    assert post_path.exists()
