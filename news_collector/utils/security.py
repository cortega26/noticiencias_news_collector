import ipaddress
import socket
from urllib.parse import urlparse


def validate_url_safety(url: str) -> None:
    """
    Validates that a URL does not point to a private or loopback address (SSRF protection).
    Raises ValueError if the URL is unsafe.

    This function resolves the DNS of the hostname and checks if any resolved IP
    is private, loopback, link-local, or reserved.

    Args:
        url: The URL to validate.

    Raises:
        ValueError: If the URL is missing a hostname or resolves to a private IP.
    """
    try:
        parsed = urlparse(url)

        # 1. Explicit Scheme Validation
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: '{scheme}'. Only http and https are allowed.")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: missing hostname")

        # Resolve hostname to IP
        # Note: socket.getaddrinfo is blocking. In async contexts, run this in a thread executor.
        try:
            ip_list = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            # We MUST fail closed on resolution errors to prevent TOCTOU or DNSrebinding bypasses
            raise ValueError(f"SSRF Protection: Failed to resolve hostname '{hostname}' ({e})") from e

        for item in ip_list:
            # item is (family, type, proto, canonname, sockaddr)
            # sockaddr is (address, port) for IPv4/v6
            ip_str = item[4][0]
            ip_obj = ipaddress.ip_address(ip_str)

            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
            ):
                raise ValueError(
                    f"SSRF Protection: Blocked access to private IP {ip_str} for {hostname}"
                )

    except Exception as e:
        if isinstance(e, ValueError):
            raise
        # Fail closed on any other unexpected error during validation
        raise ValueError(f"SSRF Protection: Validation failed due to unexpected error ({e})") from e
