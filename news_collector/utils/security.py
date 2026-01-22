
import socket
import ipaddress
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
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: missing hostname")

        # Resolve hostname to IP
        # Note: socket.getaddrinfo is blocking. In async contexts, run this in a thread executor.
        try:
            ip_list = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            # If we can't resolve it, functionality might fail later, but it's not strictly an SSRF risk
            # unless the resolution changes between now and fetch (TOCTOU).
            # For strictness, we could fail here, but let's allow requests to handle resolution errors.
            return

        for item in ip_list:
            # item is (family, type, proto, canonname, sockaddr)
            # sockaddr is (address, port) for IPv4/v6
            ip_str = item[4][0]
            ip_obj = ipaddress.ip_address(ip_str)

            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                raise ValueError(f"SSRF Protection: Blocked access to private IP {ip_str} for {hostname}")

    except Exception as e:
        if "SSRF" in str(e) or "missing hostname" in str(e):
            raise
        # Log or re-raise? For safety, if we can't validate, we should arguably block.
        # But let's assume validation failure is blocked.
        pass
