import unittest
from unittest.mock import MagicMock, patch

import requests
from news_collector.infrastructure.requests_client import RobustRequestsClient


class TestRobustRequestsClient(unittest.TestCase):

    def setUp(self):
        self.client = RobustRequestsClient(timeout=1.0)
        # Disable sleep during tests to speed up retries
        self.client._execute_request.retry.sleep = lambda x: None

    def tearDown(self):
        self.client.close()

    @patch("requests.Session.get")
    def test_success_request(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"
        mock_get.return_value = mock_resp

        resp = self.client.get("http://example.com")
        self.assertEqual(resp.text, "OK")
        mock_get.assert_called_once()

        # Verify Headers
        call_kwargs = mock_get.call_args[1]
        headers = call_kwargs["headers"]
        self.assertIn("User-Agent", headers)
        self.assertIn("NoticienciasBot", headers["User-Agent"])

    @patch("requests.Session.get")
    def test_fail_fast_on_403(self, mock_get):
        print("Testing Fail Fast 403...")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        with self.assertRaises(requests.HTTPError):
            self.client.get("http://example.com/forbidden")

        # Should NOT retry
        self.assertEqual(mock_get.call_count, 1)

    @patch("requests.Session.get")
    def test_retry_on_500(self, mock_get):
        print("Testing Retry on 500...")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        with self.assertRaises(
            requests.HTTPError
        ):  # reraise=True raises the underlying exception
            self.client.get("http://example.com/error")

        # Should retry multiple times (default 3)
        self.assertGreater(mock_get.call_count, 1)

    @patch("news_collector.infrastructure.requests_client.validate_url_safety")
    def test_ssrf_validation_called(self, mock_validate):
        with patch("requests.Session.get"):
            self.client.get("http://example.com")
            mock_validate.assert_called_with("http://example.com")


if __name__ == "__main__":
    unittest.main()
