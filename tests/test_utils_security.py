import socket
import unittest
from unittest.mock import patch

from news_collector.utils.security import validate_url_safety


class TestSecurity(unittest.TestCase):

    @patch("socket.getaddrinfo")
    def test_validate_url_safety_valid(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        ]
        # Should not raise
        validate_url_safety("https://google.com")

    @patch("socket.getaddrinfo")
    def test_validate_url_safety_private_ip(self, mock_getaddrinfo):
        # 192.168.1.1 is private
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 80))
        ]
        with self.assertRaises(ValueError) as cm:
            validate_url_safety("http://internal-site")
        self.assertIn("SSRF Protection", str(cm.exception))

    @patch("socket.getaddrinfo")
    def test_validate_url_safety_loopback(self, mock_getaddrinfo):
        # 127.0.0.1 is loopback
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]
        with self.assertRaises(ValueError) as cm:
            validate_url_safety("http://localhost")
        self.assertIn("SSRF Protection", str(cm.exception))

    def test_missing_hostname(self):
        with self.assertRaises(ValueError) as cm:
            validate_url_safety("file:///etc/passwd")
        self.assertIn("missing hostname", str(cm.exception))

    @patch("socket.getaddrinfo")
    def test_dns_resolution_error(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
        # Should silently return (feature: allow fetch failure later)
        validate_url_safety("http://nonexistent.domain")


if __name__ == "__main__":
    unittest.main()
