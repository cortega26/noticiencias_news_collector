from unittest.mock import patch

import pytest
from news_collector.utils.security import validate_url_safety


def test_validate_url_safety_public():
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock public IP (Google DNS)
        mock_dns.return_value = [(2, 1, 6, "", ("8.8.8.8", 0))]
        validate_url_safety("http://google.com")


def test_validate_url_safety_private():
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock private IP
        mock_dns.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]
        with pytest.raises(ValueError, match="SSRF Protection"):
            validate_url_safety("http://internal-service")


def test_validate_url_safety_loopback():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]
        with pytest.raises(ValueError, match="SSRF Protection"):
            validate_url_safety("http://localhost")


def test_validate_url_safety_no_hostname():
    with pytest.raises(ValueError, match="Invalid URL scheme: 'file'"):
        validate_url_safety("file:///etc/passwd")


def test_validate_url_safety_empty_hostname():
    with pytest.raises(ValueError, match="missing hostname"):
        validate_url_safety("http://")


def test_validate_url_safety_dns_resolution_failure():
    import socket

    with patch("socket.getaddrinfo", side_effect=socket.gaierror("DNS failure")):
        with pytest.raises(ValueError, match="Failed to resolve hostname"):
            validate_url_safety("http://nonexistent.invalid")


def test_validate_url_safety_unexpected_exception():
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("8.8.8.8", 0))]
        with patch("ipaddress.ip_address", side_effect=RuntimeError("unexpected")):
            with pytest.raises(ValueError, match="Validation failed"):
                validate_url_safety("http://example.com")
