"""Local Git integration coverage for publication image staging."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import git

from news_collector.components.publishing.github_publisher import GitHubPublisher
from news_collector.logic.workflows.target_repo_publication import (
    PublicationDeps,
    PublicationRequest,
    TargetRepoPublicationWorkflow,
)
from news_collector.logic.workflows.target_repo_writer import (
    PendingImageAsset,
    TargetRepoWriter,
)


class _CleanCheckoutPublisher(GitHubPublisher):
    def create_branch(self, repo, *args, **kwargs):
        assert not repo.is_dirty(untracked_files=True)
        return super().create_branch(repo, *args, **kwargs)


class _Stages:
    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(self, name: str, success: bool, **_details) -> None:
        self.names.append(name)


def _configure_git_identity(repo: git.Repo) -> None:
    with repo.config_writer() as config:
        config.set_value("user", "name", "News Collector Integration")
        config.set_value("user", "email", "integration@example.invalid")


def test_image_is_materialized_after_clean_branch_setup_and_pushed_locally(
    tmp_path: Path,
):
    bare_path = tmp_path / "origin.git"
    bare_repo = git.Repo.init(bare_path, bare=True)
    seed_path = tmp_path / "seed"
    seed_path.mkdir()
    seed_repo = git.Repo.init(seed_path)
    _configure_git_identity(seed_repo)
    seed_repo.git.checkout("-b", "main")
    (seed_path / "README.md").write_text("base\n", encoding="utf-8")
    seed_repo.index.add(["README.md"])
    seed_repo.index.commit("Seed target repository")
    seed_repo.create_remote("origin", str(bare_path))
    seed_repo.git.push("-u", "origin", "main")
    bare_repo.git.symbolic_ref("HEAD", "refs/heads/main")

    target_dir = tmp_path / "target"
    target_repo = git.Repo.clone_from(str(bare_path), target_dir)
    _configure_git_identity(target_repo)
    assert not target_repo.is_dirty(untracked_files=True)

    database = MagicMock()
    publisher = _CleanCheckoutPublisher()
    pr_orchestrator = SimpleNamespace(
        ensure_draft_branch=lambda *_args, **_kwargs: None,
        create_pr=lambda **_kwargs: SimpleNamespace(
            pr_url="https://example.invalid/pull/1"
        ),
    )
    request = PublicationRequest(
        article={"id": "42", "title": "Test publication"},
        article_id="42",
        numeric_id=42,
        output_filename="2024-01-25-test.md",
        refined_content=(
            "---\ntitle: Test publication\n"
            'image: "~/assets/images/hero.png"\n---\n\nBody\n'
        ),
        grounding_notes="",
        target_repo_obj=target_repo,
        target_dir=target_dir,
        attempts_dir=tmp_path / "attempts",
        pending_image_asset=PendingImageAsset(
            filename="hero.png", content=b"original-editorial-image"
        ),
    )
    stages = _Stages()

    outcome = TargetRepoPublicationWorkflow().publish(
        request,
        PublicationDeps(
            writer=TargetRepoWriter(),
            git=publisher,
            pr_orchestrator=pr_orchestrator,
            db=database,
        ),
        stages,
    )

    assert outcome.success is True
    assert outcome.branch_name == "content/update-2024-01-25-test"
    assert (
        stages.names.index("branch_created")
        < stages.names.index("image_asset_written")
        < stages.names.index("file_written")
    )
    assert not target_repo.is_dirty(untracked_files=True)

    pushed_branch = bare_repo.refs[outcome.branch_name]
    image_blob = pushed_branch.commit.tree / "src/assets/images/hero.png"
    post_blob = pushed_branch.commit.tree / "src/content/posts/2024-01-25-test.md"
    assert image_blob.data_stream.read() == b"original-editorial-image"
    assert b"~/assets/images/hero.png" in post_blob.data_stream.read()
    database.release_article_publishing.assert_not_called()
