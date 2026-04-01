"""Tests for A-04: Detect existing PR on GitHub 422 response (F-0016)."""

from unittest.mock import MagicMock, patch

import pytest

from news_collector.components.publishing.github_publisher import GitHubPublisher


@pytest.fixture
def publisher():
    return GitHubPublisher(github_token="fake-token")


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class TestPR422Recovery:
    """A-04 / F-0016: 422 response should attempt to recover existing PR."""

    def test_pr_422_returns_existing_url(self, publisher):
        """When PR creation returns 422 and an open PR exists, return its URL."""
        existing_pr_url = "https://github.com/owner/repo/pull/42"

        post_response = _FakeResponse(422, text="Validation Failed")
        get_response = _FakeResponse(
            200,
            json_data=[{"html_url": existing_pr_url}],
        )

        with patch(
            "news_collector.components.publishing.github_publisher.requests"
        ) as mock_requests:
            mock_requests.post.return_value = post_response
            mock_requests.get.return_value = get_response

            result = publisher.create_pull_request(
                repo_url="https://github.com/owner/repo.git",
                branch_name="article/test-branch",
                title="Test PR",
                body="Test body",
            )

        assert result == existing_pr_url
        # Verify the GET was called with correct params
        mock_requests.get.assert_called_once()
        call_kwargs = mock_requests.get.call_args
        assert call_kwargs[1]["params"]["head"] == "owner:article/test-branch"
        assert call_kwargs[1]["params"]["state"] == "open"

    def test_pr_422_no_existing_pr_raises(self, publisher):
        """When PR creation returns 422 but no open PR exists, raise."""
        post_response = _FakeResponse(422, text="Validation Failed")
        get_response = _FakeResponse(200, json_data=[])  # No PRs found

        with patch(
            "news_collector.components.publishing.github_publisher.requests"
        ) as mock_requests:
            mock_requests.post.return_value = post_response
            mock_requests.get.return_value = get_response

            with pytest.raises(Exception, match="PR Creation failed"):
                publisher.create_pull_request(
                    repo_url="https://github.com/owner/repo.git",
                    branch_name="article/test-branch",
                    title="Test PR",
                    body="Test body",
                )

    def test_pr_422_search_api_fails_raises(self, publisher):
        """When PR creation returns 422 and the search API fails, raise."""
        post_response = _FakeResponse(422, text="Validation Failed")
        get_response = _FakeResponse(500, text="Internal Server Error")

        with patch(
            "news_collector.components.publishing.github_publisher.requests"
        ) as mock_requests:
            mock_requests.post.return_value = post_response
            mock_requests.get.return_value = get_response

            with pytest.raises(Exception, match="PR Creation failed"):
                publisher.create_pull_request(
                    repo_url="https://github.com/owner/repo.git",
                    branch_name="article/test-branch",
                    title="Test PR",
                    body="Test body",
                )

    def test_pr_201_still_works(self, publisher):
        """Normal 201 path is unaffected by the 422 recovery logic."""
        pr_url = "https://github.com/owner/repo/pull/99"
        post_response = _FakeResponse(201, json_data={"html_url": pr_url})

        with patch(
            "news_collector.components.publishing.github_publisher.requests"
        ) as mock_requests:
            mock_requests.post.return_value = post_response

            result = publisher.create_pull_request(
                repo_url="https://github.com/owner/repo.git",
                branch_name="article/test-branch",
                title="Test PR",
                body="Test body",
            )

        assert result == pr_url
        mock_requests.get.assert_not_called()
