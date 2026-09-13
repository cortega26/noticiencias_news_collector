import os
import types
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import git
import pytest

from news_collector.components.publishing.github_publisher import GitHubPublisher


@pytest.fixture
def publisher():
    return GitHubPublisher(github_token="fake_token")


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.heads = {}
    repo.refs = []
    repo.git_dir = "/tmp/non-existent-git-dir"
    repo.git = MagicMock()
    repo.active_branch = MagicMock()
    repo.active_branch.name = "main"
    repo.index = MagicMock()
    repo.is_dirty.return_value = False
    return repo


def test_clone_repo(publisher):
    # Patch where it is used primarily, if possible, or global git.Repo
    # Use string path that matches implementation import if "from git import Repo"
    # But implementation uses "import git", then "git.Repo.clone_from"
    with patch(
        "news_collector.components.publishing.github_publisher.git.Repo.clone_from"
    ) as mock_clone:
        with patch.object(publisher, "_cleanup_dir") as mock_clean:
            target_dir = Path("/tmp/test_repo")
            publisher.clone_repo("https://github.com/org/repo.git", target_dir)

            mock_clean.assert_called_once_with(target_dir)
            mock_clone.assert_called_once()
            args, _ = mock_clone.call_args
            # Verify auth token injection
            assert "x-access-token" in args[0]


def test_create_branch_remote_absent_resets_stale_local_to_deterministic_base(
    publisher, mock_repo
):
    mock_head = MagicMock()
    mock_repo.heads = {"feat/test-slug-123": mock_head}
    mock_repo.refs = [types.SimpleNamespace(name="origin/main")]

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.git.checkout.assert_called_once_with(
        "-B", "feat/test-slug-123", "origin/main", env=ANY
    )
    mock_head.checkout.assert_not_called()
    mock_repo.git.fetch.assert_called_once()


def test_create_branch_remote_absent_resets_correct_local_to_deterministic_base(
    publisher, mock_repo
):
    mock_head = MagicMock()
    mock_repo.heads = {"feat/test-slug-123": mock_head}
    mock_repo.refs = [types.SimpleNamespace(name="origin/main")]

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.git.checkout.assert_called_once_with(
        "-B", "feat/test-slug-123", "origin/main", env=ANY
    )
    mock_head.checkout.assert_not_called()


def test_create_branch_remote_absent_without_base_ref_fails(publisher, mock_repo):
    mock_repo.refs = []

    with pytest.raises(RuntimeError) as err:
        publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert "Deterministic base ref origin/main not found" in str(err.value)


def test_create_branch_remote_exists(publisher, mock_repo):
    mock_repo.refs = [types.SimpleNamespace(name="origin/feat/test-slug-123")]

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.git.fetch.assert_called_once()
    mock_repo.git.checkout.assert_called_once_with(
        "-B", "feat/test-slug-123", "origin/feat/test-slug-123", env=ANY
    )
    mock_repo.git.rebase.assert_called_once_with("origin/feat/test-slug-123", env=ANY)


def test_create_branch_fetch_failure_triggers_cleanup(publisher, mock_repo):
    mock_repo.git.fetch.side_effect = git.GitCommandError("fetch", 1, stderr="network")

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(git.GitCommandError):
            publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    cleanup_mock.assert_called_once_with(mock_repo, "feat/test-slug-123", ANY)


def test_create_branch_remote_rebase_failure_triggers_cleanup(publisher, mock_repo):
    mock_repo.refs = [types.SimpleNamespace(name="origin/feat/test-slug-123")]
    mock_repo.git.rebase.side_effect = git.GitCommandError(
        "rebase", 1, stderr="conflict"
    )

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(git.GitCommandError):
            publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    cleanup_mock.assert_called_once_with(mock_repo, "feat/test-slug-123", ANY)


def test_create_branch_remote_rebase_failure_executes_cleanup_steps(
    publisher, mock_repo
):
    mock_repo.refs = [types.SimpleNamespace(name="origin/feat/test-slug-123")]
    mock_repo.git.rebase.side_effect = git.GitCommandError(
        "rebase", 1, stderr="conflict"
    )

    with pytest.raises(git.GitCommandError):
        publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    mock_repo.git.rebase.assert_any_call("--abort", env=ANY)
    mock_repo.git.merge.assert_called_once_with("--abort", env=ANY)
    mock_repo.git.cherry_pick.assert_called_once_with("--abort", env=ANY)
    mock_repo.git.revert.assert_called_once_with("--abort", env=ANY)
    mock_repo.git.checkout.assert_any_call("feat/test-slug-123", env=ANY)


def test_commit_and_push_dirty(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True

    publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    mock_repo.git.add.assert_called_once_with(A=True)
    mock_repo.index.commit.assert_called_once_with("Commit Msg")
    mock_repo.git.push.assert_called_once()


def test_commit_and_push_retry_non_fast_forward_success(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = [
        git.GitCommandError(
            "push", 1, stderr="rejected (non-fast-forward): tip is behind"
        ),
        None,
    ]

    publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    assert mock_repo.git.push.call_count == 2
    mock_repo.git.fetch.assert_called_once_with("origin", "--prune", env=ANY)
    mock_repo.git.rebase.assert_called_once_with("origin/feat/branch", env=ANY)


def test_commit_and_push_retry_non_fast_forward_conflict(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = git.GitCommandError(
        "push", 1, stderr="rejected (non-fast-forward): tip is behind"
    )
    mock_repo.git.rebase.side_effect = git.GitCommandError(
        "rebase", 1, stderr="CONFLICT (content): Merge conflict in file.md"
    )
    mock_repo.git.diff.return_value = "src/content/posts/file.md\n"

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(RuntimeError) as err:
            publisher.commit_and_push(mock_repo, "Commit Msg", "content/update-article")

    message = str(err.value)
    assert "content/update-article" in message
    assert "src/content/posts/file.md" in message
    assert "No force push was attempted." in message
    cleanup_mock.assert_called_once_with(mock_repo, "content/update-article", ANY)
    assert mock_repo.git.push.call_count == 1


def test_commit_and_push_clean(publisher, mock_repo):
    mock_repo.is_dirty.return_value = False

    publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    mock_repo.git.add.assert_not_called()
    mock_repo.git.push.assert_not_called()


def test_commit_and_push_non_non_fast_forward_error_cleans_state(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = git.GitCommandError(
        "push", 1, stderr="permission denied"
    )

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(RuntimeError) as err:
            publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    assert "No force push was attempted." in str(err.value)
    cleanup_mock.assert_called_once_with(mock_repo, "feat/branch", ANY)


def test_commit_and_push_add_failure_cleans_state(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.add.side_effect = RuntimeError("add failed")

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(RuntimeError) as err:
            publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    assert "add failed" in str(err.value)
    cleanup_mock.assert_called_once_with(mock_repo, "feat/branch", ANY)


def test_commit_and_push_retry_fetch_error_cleans_state(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = git.GitCommandError(
        "push", 1, stderr="tip of your current branch is behind"
    )
    mock_repo.git.fetch.side_effect = git.GitCommandError("fetch", 1, stderr="network")

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(RuntimeError) as err:
            publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    assert "No force push was attempted." in str(err.value)
    cleanup_mock.assert_called_once_with(mock_repo, "feat/branch", ANY)


def test_commit_and_push_retries_at_most_once(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True
    mock_repo.git.push.side_effect = [
        git.GitCommandError("push", 1, stderr="rejected (non-fast-forward)"),
        git.GitCommandError("push", 1, stderr="rejected (non-fast-forward)"),
    ]

    with patch.object(publisher, "_ensure_clean_exit_state") as cleanup_mock:
        with pytest.raises(RuntimeError) as err:
            publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    assert "remote advanced again during retry" in str(err.value)
    assert mock_repo.git.push.call_count == 2
    cleanup_mock.assert_called_once_with(mock_repo, "feat/branch", ANY)


@pytest.mark.parametrize(
    "stderr,stdout",
    [
        ("rejected (non-fast-forward)", ""),
        ("Updates were rejected because the tip of your current branch is behind", ""),
        ("", "error: failed to push some refs\nupdates were rejected"),
        ("hint: fetch first", ""),
    ],
)
def test_is_non_fast_forward_variants(publisher, stderr, stdout):
    err = git.GitCommandError("push", 1, stderr=stderr, stdout=stdout)
    assert publisher._is_non_fast_forward(err) is True


def test_is_non_fast_forward_variant_negative(publisher):
    err = git.GitCommandError("push", 1, stderr="remote: permission denied")
    assert publisher._is_non_fast_forward(err) is False


def test_ensure_clean_exit_state_raises_when_repo_is_dirty(publisher, mock_repo):
    mock_repo.active_branch.name = "feat/branch"
    mock_repo.is_dirty.return_value = True

    with pytest.raises(RuntimeError) as err:
        publisher._ensure_clean_exit_state(mock_repo, "feat/branch", None)

    assert "dirty after cleanup" in str(err.value)


def test_ensure_clean_exit_state_aborts_operations_and_recovers_branch(
    publisher, mock_repo
):
    mock_repo.active_branch.name = "main"
    mock_repo.is_dirty.return_value = False

    publisher._ensure_clean_exit_state(mock_repo, "feat/branch", None)

    mock_repo.git.rebase.assert_called_once_with("--abort", env=None)
    mock_repo.git.merge.assert_called_once_with("--abort", env=None)
    mock_repo.git.cherry_pick.assert_called_once_with("--abort", env=None)
    mock_repo.git.revert.assert_called_once_with("--abort", env=None)
    mock_repo.git.checkout.assert_called_once_with("feat/branch", env=None)


def test_create_branch_uses_configured_base_branch():
    publisher = GitHubPublisher(github_token="fake_token", base_branch="trunk")
    mock_repo = MagicMock()
    mock_repo.heads = {}
    mock_repo.refs = [types.SimpleNamespace(name="origin/trunk")]
    mock_repo.git = MagicMock()
    mock_repo.active_branch = MagicMock()
    mock_repo.active_branch.name = "trunk"
    mock_repo.index = MagicMock()
    mock_repo.git_dir = "/tmp/non-existent-git-dir"
    mock_repo.is_dirty.return_value = False

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.git.checkout.assert_called_once_with(
        "-B", "feat/test-slug-123", "origin/trunk", env=ANY
    )


def test_create_branch_missing_configured_base_fails_fast():
    publisher = GitHubPublisher(github_token="fake_token", base_branch="trunk")
    mock_repo = MagicMock()
    mock_repo.heads = {}
    mock_repo.refs = []
    mock_repo.git = MagicMock()
    mock_repo.active_branch = MagicMock()
    mock_repo.active_branch.name = "main"
    mock_repo.index = MagicMock()
    mock_repo.git_dir = "/tmp/non-existent-git-dir"
    mock_repo.is_dirty.return_value = False

    with pytest.raises(RuntimeError) as err:
        publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert "Deterministic base ref origin/trunk not found" in str(err.value)


def test_create_pull_request_success(publisher):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"html_url": "http://pr/1"}
        mock_post.return_value = mock_resp

        url = publisher.create_pull_request(
            "https://github.com/org/repo.git", "feat/b", "Title", "Body"
        )

        assert url == "http://pr/1"
        assert mock_post.called
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["title"] == "Title"
        assert payload["head"] == "feat/b"


def test_create_pull_request_uses_configured_base_by_default():
    publisher = GitHubPublisher(github_token="fake_token", base_branch="trunk")
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"html_url": "http://pr/1"}
        mock_post.return_value = mock_resp

        publisher.create_pull_request(
            "https://github.com/org/repo.git", "feat/b", "Title", "Body"
        )

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["base"] == "trunk"


def test_create_pull_request_passes_timeout(publisher):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"html_url": "http://pr/1"}
        mock_post.return_value = mock_resp

        publisher.create_pull_request(
            "https://github.com/org/repo.git", "feat/b", "Title", "Body"
        )

        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == 15


def test_create_pull_request_422_recovery_passes_timeout(publisher):
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "A pull request already exists"
        mock_post.return_value = mock_resp

        mock_search = MagicMock()
        mock_search.status_code = 200
        mock_search.json.return_value = [{"html_url": "http://pr/existing"}]
        mock_get.return_value = mock_search

        url = publisher.create_pull_request(
            "https://github.com/org/repo.git", "feat/b", "Title", "Body"
        )

        assert url == "http://pr/existing"
        _, post_kwargs = mock_post.call_args
        assert post_kwargs["timeout"] == 15
        _, get_kwargs = mock_get.call_args
        assert get_kwargs["timeout"] == 15


def test_safe_repo_url(publisher):
    # Test token injection
    clean = "https://github.com/org/repo.git"
    safe = publisher._safe_repo_url(clean)
    assert "x-access-token" in safe

    ssh = "git@github.com:org/repo.git"
    safe_ssh = publisher._safe_repo_url(ssh)
    assert "https://x-access-token" in safe_ssh


def test_askpass_generation(publisher):
    with patch("pathlib.Path.write_text") as mock_write, patch("os.chmod"):
        script_path = publisher._ensure_askpass_script()
        assert script_path is not None
        mock_write.assert_called_once()


def _no_token_publisher():
    with patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
        return GitHubPublisher(github_token="")


def test_strip_credentials_removes_embedded_token(publisher):
    assert (
        publisher._strip_credentials("https://user:pass@github.com/org/repo.git")
        == "https://github.com/org/repo.git"
    )
    plain = "https://github.com/org/repo.git"
    assert publisher._strip_credentials(plain) == plain


def test_safe_repo_url_without_token_returns_url_unchanged():
    publisher = _no_token_publisher()
    clean = "https://github.com/org/repo.git"
    assert publisher._safe_repo_url(clean) == clean


def test_safe_repo_url_non_github_host_returns_url_unchanged(publisher):
    other = "https://gitlab.example.com/org/repo.git"
    assert publisher._safe_repo_url(other) == other


def test_ensure_askpass_script_without_token_raises():
    publisher = _no_token_publisher()
    with pytest.raises(RuntimeError, match="GitHub token required"):
        publisher._ensure_askpass_script()


def test_ensure_askpass_script_returns_cached_path(publisher, tmp_path):
    cached = tmp_path / "askpass.sh"
    cached.write_text("#!/bin/sh\n")
    publisher._askpass_path = cached

    with patch("pathlib.Path.write_text") as mock_write:
        assert publisher._ensure_askpass_script() == cached
        mock_write.assert_not_called()


def test_ensure_askpass_script_windows_content(publisher, tmp_path):
    from pathlib import PosixPath

    def _posix_path(*args, **kwargs):
        return PosixPath(*args, **kwargs)

    with (
        patch.object(os, "name", "nt"),
        patch(
            "news_collector.components.publishing.github_publisher.Path",
            side_effect=_posix_path,
        ),
        patch("tempfile.gettempdir", return_value=str(tmp_path)),
        patch("pathlib.Path.write_text") as mock_write,
    ):
        script_path = publisher._ensure_askpass_script()

    assert str(script_path).endswith(".cmd")
    written = mock_write.call_args[0][0]
    assert "@echo off" in written


def test_ensure_askpass_script_posix_writes_executable(publisher, tmp_path):
    import stat

    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        script_path = publisher._ensure_askpass_script()

    assert script_path.exists()
    assert "printf" in script_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(script_path.stat().st_mode) == 0o700


def test_auth_env_without_token_returns_empty():
    assert _no_token_publisher()._auth_env() == {}


def test_get_conflict_files_returns_empty_on_git_error(publisher, mock_repo):
    mock_repo.git.diff.side_effect = git.GitCommandError("diff", 1)
    assert publisher._get_conflict_files(mock_repo) == []


def test_get_git_state_markers_returns_empty_when_git_dir_unreadable(publisher):
    class BrokenGitDirRepo:
        git = MagicMock()

        @property
        def git_dir(self):
            raise Exception("unreadable")

    assert publisher._get_git_state_markers(BrokenGitDirRepo()) == []


def test_get_git_state_markers_detects_marker_file(publisher, tmp_path):
    (tmp_path / "MERGE_HEAD").write_text("abc123")
    repo = MagicMock()
    repo.git_dir = str(tmp_path)
    assert publisher._get_git_state_markers(repo) == ["MERGE_HEAD"]


def test_ensure_clean_exit_state_detached_head_recovers(publisher):
    class DetachedHeadRepo:
        git = MagicMock()
        git_dir = "/tmp/non-existent-git-dir"

        @property
        def active_branch(self):
            raise Exception("detached HEAD")

        @staticmethod
        def is_dirty(untracked_files=False):
            return False

    repo = DetachedHeadRepo()
    publisher._ensure_clean_exit_state(repo, "feat/branch", None)

    repo.git.checkout.assert_called_once_with("feat/branch", env=None)


def test_ensure_clean_exit_state_falls_back_to_base_branch(publisher, mock_repo):
    mock_repo.active_branch.name = "main"
    mock_repo.is_dirty.return_value = False
    mock_repo.git.checkout.side_effect = [
        git.GitCommandError("checkout", 1),
        None,
    ]

    publisher._ensure_clean_exit_state(mock_repo, "feat/branch", None)

    assert mock_repo.git.checkout.call_args_list == [
        call("feat/branch", env=None),
        call("main", env=None),
    ]


def test_ensure_clean_exit_state_raises_on_lingering_markers(publisher, tmp_path):
    (tmp_path / "MERGE_HEAD").write_text("abc123")
    repo = MagicMock()
    repo.git_dir = str(tmp_path)
    repo.git = MagicMock()
    repo.active_branch = MagicMock()
    repo.active_branch.name = "feat/branch"
    repo.is_dirty.return_value = False

    with pytest.raises(RuntimeError, match="in-progress git state"):
        publisher._ensure_clean_exit_state(repo, "feat/branch", None)


def test_cleanup_on_failure_reports_cleanup_error(publisher, mock_repo):
    with patch.object(
        publisher,
        "_ensure_clean_exit_state",
        side_effect=RuntimeError("cleanup boom"),
    ):
        with pytest.raises(RuntimeError, match="Cleanup verification failed"):
            with publisher._cleanup_on_failure(
                repo=mock_repo, branch_name="feat/b", env=None, operation="Push"
            ):
                raise ValueError("original failure")


def test_cleanup_dir_removes_existing_directory(publisher, tmp_path):
    target = tmp_path / "old-clone"
    target.mkdir()
    (target / "file.txt").write_text("data")

    publisher._cleanup_dir(target)

    assert not target.exists()


def test_create_branch_without_explicit_name_uses_random_suffix(publisher, mock_repo):
    mock_repo.refs = [types.SimpleNamespace(name="origin/main")]

    branch = publisher.create_branch(mock_repo, "news/article")

    assert branch.startswith("news/article-")
    suffix = branch[len("news/article-") :]
    assert len(suffix) == 8
    int(suffix, 16)


def test_create_pull_request_failure_raises(publisher):
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server exploded"
        mock_post.return_value = mock_resp

        with pytest.raises(Exception, match="PR Creation failed"):
            publisher.create_pull_request(
                "https://github.com/org/repo.git", "feat/b", "Title", "Body"
            )
