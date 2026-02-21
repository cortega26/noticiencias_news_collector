from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from news_collector.components.publishing.github_publisher import GitHubPublisher


@pytest.fixture
def publisher():
    return GitHubPublisher(github_token="fake_token")


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.heads = {}
    repo.git = MagicMock()
    repo.index = MagicMock()
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


def test_create_branch_new(publisher, mock_repo):
    mock_repo.heads = {}  # Empty heads
    mock_head = MagicMock()
    mock_repo.create_head.return_value = mock_head

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.create_head.assert_called_once_with("feat/test-slug-123")
    mock_head.checkout.assert_called_once()


def test_create_branch_existing(publisher, mock_repo):
    mock_head = MagicMock()
    mock_repo.heads = {"feat/test-slug-123": mock_head}

    branch = publisher.create_branch(mock_repo, "feat/test", explicit_name="slug-123")

    assert branch == "feat/test-slug-123"
    mock_repo.create_head.assert_not_called()
    mock_head.checkout.assert_called_once()


def test_commit_and_push_dirty(publisher, mock_repo):
    mock_repo.is_dirty.return_value = True

    publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    mock_repo.git.add.assert_called_once_with(A=True)
    mock_repo.index.commit.assert_called_once_with("Commit Msg")
    mock_repo.git.push.assert_called_once()


def test_commit_and_push_clean(publisher, mock_repo):
    mock_repo.is_dirty.return_value = False

    publisher.commit_and_push(mock_repo, "Commit Msg", "feat/branch")

    mock_repo.git.add.assert_not_called()
    mock_repo.git.push.assert_not_called()


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
