"""
CRIT-01 SSRF protection tests for fetch_full_article().

Proves that unsafe URLs are blocked BEFORE any network request is attempted,
and that safe URLs pass validation (with mocked request and DNS).
"""

import unittest
from unittest.mock import MagicMock, patch

from news_collector.utils.full_text import fetch_full_article


class TestFullTextSSRFProtection(unittest.TestCase):
    """Verifies SSRF guard in fetch_full_article() blocks unsafe URLs."""

    def setUp(self):
        self.mock_response = MagicMock()
        self.mock_response.raise_for_status = MagicMock()
        self.mock_response.content = (
            b"<html><body><article>Should not reach here</article></body></html>"
        )

    # ── Blocking tests: request must NEVER be called ──

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("169.254.169.254", 0))],
    )
    def test_blocks_cloud_metadata_url(self, _mock_dns, mock_get):
        """Cloud metadata endpoint (169.254.169.254) must be blocked."""
        result = fetch_full_article("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(result, "")
        mock_get.assert_not_called()

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 0))],
    )
    def test_blocks_loopback(self, _mock_dns, mock_get):
        """Loopback address (127.0.0.1) must be blocked."""
        result = fetch_full_article("http://127.0.0.1/")
        self.assertEqual(result, "")
        mock_get.assert_not_called()

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 0))],
    )
    def test_blocks_localhost(self, _mock_dns, mock_get):
        """localhost must be blocked (resolves to 127.0.0.1)."""
        result = fetch_full_article("http://localhost/")
        self.assertEqual(result, "")
        mock_get.assert_not_called()

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("10.0.0.1", 0))],
    )
    def test_blocks_private_rfc1918(self, _mock_dns, mock_get):
        """RFC 1918 private addresses (10.x.x.x) must be blocked."""
        result = fetch_full_article("http://internal-service.local/")
        self.assertEqual(result, "")
        mock_get.assert_not_called()

    @patch("news_collector.utils.full_text.requests.get")
    def test_blocks_non_http_scheme(self, mock_get):
        """Non-HTTP schemes (file://) must be blocked."""
        result = fetch_full_article("file:///etc/passwd")
        self.assertEqual(result, "")
        mock_get.assert_not_called()

    # ── Fail-closed: returns empty string on rejection ──

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("169.254.169.254", 0))],
    )
    def test_ssrf_rejection_returns_empty_string(self, _mock_dns, mock_get):
        """Unsafe URLs must return '' (fail-closed), not raise."""
        result = fetch_full_article("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(result, "")

    # ── Safe URL: validation passes, request is mocked ──

    @patch("news_collector.utils.full_text.requests.get")
    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("93.184.216.34", 0))],
    )
    def test_safe_url_passes_validation(self, _mock_dns, mock_get):
        """Public URL passes validation; request proceeds (mocked)."""
        self.mock_response.content = (
            b"<html><body><article>Real article</article></body></html>"
        )
        mock_get.return_value = self.mock_response

        result = fetch_full_article("http://example.com/article")
        self.assertEqual(result, "Real article")
        mock_get.assert_called_once()

    # ── Session path also validates ──

    @patch(
        "news_collector.utils.security.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("169.254.169.254", 0))],
    )
    def test_session_path_also_blocks_ssrf(self, _mock_dns):
        """SSRF validation applies even when a session is provided."""
        session = MagicMock()
        result = fetch_full_article(
            "http://169.254.169.254/latest/meta-data/", session=session
        )
        self.assertEqual(result, "")
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
