import unittest
from unittest.mock import MagicMock, patch

import requests

from news_collector.infrastructure.requests_client import RobustRequestsClient


class TestRobustRequestsClient(unittest.TestCase):

    def setUp(self):
        self.client = RobustRequestsClient(timeout=1.0)
        # Disable sleep during tests to speed up retries
        self.client._retry_sleep = lambda x: None

    def tearDown(self):
        self.client.close()

    @patch("requests.adapters.HTTPAdapter.send")
    def test_success_request(self, mock_send):
        mock_resp = MagicMock()
        mock_resp.url = "http://example.com"
        mock_resp.headers = {}
        mock_resp.is_redirect = False
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_send.return_value = mock_resp

        with patch("news_collector.infrastructure.requests_client.validate_url_safety"):
            resp = self.client.get("http://example.com")
        self.assertEqual(resp.text, "OK")
        mock_send.assert_called_once()

        # Verify Headers
        call_kwargs = mock_send.call_args[1]
        # In HTTPAdapter.send, the request object is passed as the first positional arg
        request_obj = mock_send.call_args[0][0]
        headers = request_obj.headers
        self.assertIn("User-Agent", headers)
        self.assertIn("NoticienciasBot", headers["User-Agent"])

    @patch("requests.adapters.HTTPAdapter.send")
    def test_fail_fast_on_403(self, mock_send):
        print("Testing Fail Fast 403...")
        mock_resp = MagicMock()
        mock_resp.url = "http://example.com/forbidden"
        mock_resp.headers = {}
        mock_resp.is_redirect = False
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_send.return_value = mock_resp

        with patch("news_collector.infrastructure.requests_client.validate_url_safety"):
            with self.assertRaises(requests.HTTPError):
                self.client.get("http://example.com/forbidden")

        # Should NOT retry
        self.assertEqual(mock_send.call_count, 1)

    @patch("requests.adapters.HTTPAdapter.send")
    def test_retry_on_500(self, mock_send):
        print("Testing Retry on 500...")
        mock_resp = MagicMock()
        mock_resp.url = "http://example.com/error"
        mock_resp.headers = {}
        mock_resp.is_redirect = False
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_send.return_value = mock_resp

        with patch("news_collector.infrastructure.requests_client.validate_url_safety"):
            with self.assertRaises(
                requests.HTTPError
            ):  # reraise=True raises the underlying exception
                self.client.get("http://example.com/error")

        # Should retry multiple times (default 3)
        self.assertGreater(mock_send.call_count, 1)

    @patch("news_collector.infrastructure.requests_client.validate_url_safety")
    def test_ssrf_validation_called(self, mock_validate):
        with patch("requests.adapters.HTTPAdapter.send") as mock_send:
            mock_resp = MagicMock()
            mock_resp.url = "http://example.com"
            mock_resp.headers = {}
            mock_resp.is_redirect = False
            mock_resp.status_code = 200
            mock_send.return_value = mock_resp

            self.client.get("http://example.com")
            mock_validate.assert_called_with("http://example.com/")


if __name__ == "__main__":
    unittest.main()


def _retry_state(status: int | None, retry_after: str | None = None):
    from types import SimpleNamespace

    import requests

    response = None
    if status is not None:
        response = requests.Response()
        response.status_code = status
        if retry_after is not None:
            response.headers["Retry-After"] = retry_after
    exc = requests.HTTPError("boom", response=response)
    outcome = SimpleNamespace(failed=True, exception=lambda: exc)
    return SimpleNamespace(outcome=outcome, attempt_number=1)


def test_rate_limit_wait_honors_retry_after_and_caps():
    from news_collector.infrastructure.requests_client import _rate_limit_wait

    assert _rate_limit_wait(_retry_state(429, "12"), lambda s: 1.0) == 12.0
    assert _rate_limit_wait(_retry_state(429, "999"), lambda s: 1.0) == 30.0
    assert _rate_limit_wait(_retry_state(429), lambda s: 1.0) == 5.0
    assert _rate_limit_wait(_retry_state(503), lambda s: 1.5) == 1.5


def test_ssl_errors_are_not_retried():
    import requests

    from news_collector.infrastructure.requests_client import _is_retryable_error

    assert _is_retryable_error(requests.exceptions.SSLError("bad cert")) is False
    assert _is_retryable_error(requests.exceptions.ConnectionError("reset")) is True


def test_default_headers_do_not_advertise_brotli():
    """brotli is not installed: advertising 'br' yields undecoded garbage bodies."""
    client = RobustRequestsClient(timeout=1.0)
    try:
        encodings = client.session.headers["Accept-Encoding"]
    finally:
        client.close()
    assert "br" not in [e.strip() for e in encodings.split(",")]
    assert "gzip" in encodings
