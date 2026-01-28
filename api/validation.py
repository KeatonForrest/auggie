"""Input validation for URLs and other user-supplied data."""

import ipaddress
import socket
from urllib.parse import urlparse


# Blocked TLDs and patterns
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def validate_company_url(url: str) -> str:
    """Validate and normalize a company URL. Raises ValueError if unsafe.

    Checks:
    - Valid URL format with http/https scheme
    - Not a private/internal IP (SSRF protection)
    - Not localhost or loopback
    - Has a valid public hostname
    """
    url = normalize_url(url)
    parsed = urlparse(url)

    # Must be http or https
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname")

    # Block obvious localhost/loopback
    if hostname in _BLOCKED_HOSTS:
        raise ValueError("Internal URLs are not allowed")

    # Resolve hostname and check for private IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise ValueError("URL resolves to a private/internal address")
        except ValueError as e:
            if "private" in str(e) or "internal" in str(e):
                raise
            # Skip unparseable addresses
            continue

    return url
