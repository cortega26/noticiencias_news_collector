"""Utilities for deterministic URL canonicalization.

Rules implemented:
- Lower-case scheme/host and remove default ports (80/443).
- Strip common tracking parameters (utm_*, fbclid, gclid, etc.).
- Remove AMP/mobile variants (hosts prefixed with www./m./mobile./amp. and
  trailing /amp or ?amp flags) when safe.
- Collapse duplicate slashes, decode/encode path segments, remove fragments.
- Sort query parameters alphabetically; drop empty values and benign markers.
- Default scheme to https when missing.

The goal is to reduce duplicate URLs pointing to the same resource while
preserving meaningful distinctions (e.g., different article IDs).
"""

from __future__ import annotations

import posixpath
import re
from functools import lru_cache
from typing import Callable, Iterable, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

TRACKING_PARAM_PREFIXES: Tuple[str, ...] = (
    "utm_",
    "icid",
)

TRACKING_PARAMS: Tuple[str, ...] = (
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "amp",
    "amp_js_v",
    "amp_gsa",
    "sscid",
    "igshid",
    "spm",
    "ref",
)

BENIGN_EMPTY_PARAMS: Tuple[str, ...] = ("",)  # Remove stray empty keys

MOBILE_HOST_PREFIXES: Tuple[str, ...] = (
    "www.",
    "m.",
    "mobile.",
    "amp.",
)

AMP_PATH_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"/amp/?$", re.IGNORECASE),
    re.compile(r"\.amp$", re.IGNORECASE),
)


SAFE_PATH_CHARS = "@:$&'()*+,;=-._~!%/"


def _clean_host(host: str) -> str:
    host = host.lower()
    for prefix in MOBILE_HOST_PREFIXES:
        if not host.startswith(prefix):
            continue
        remainder = host[len(prefix) :]
        if not remainder or "." not in remainder:
            continue
        host = remainder
    return host


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    decoded = unquote(path)
    decoded = re.sub(r"//+", "/", decoded)
    normalized = posixpath.normpath(decoded)
    if decoded.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    if normalized == ".":
        normalized = "/"
    return quote(normalized, safe=SAFE_PATH_CHARS)


def _filter_query_params(pairs: Iterable[Tuple[str, str]]) -> Iterable[Tuple[str, str]]:
    seen = set()
    for key, value in pairs:
        key_lower = key.lower()
        if key_lower in BENIGN_EMPTY_PARAMS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
            continue
        if key_lower in TRACKING_PARAMS:
            continue
        if key_lower == "amp" and value in ("1", "true", "amp"):
            continue
        if value == "":
            continue
        pair = (key_lower, value)
        if pair in seen:
            continue
        seen.add(pair)
        yield pair


def _canonicalize_url_impl(url: str) -> str:  # noqa: C901
    """Canonicalize a URL string as per the rule set."""
    if not url:
        return url

    url = url.strip()
    if not url:
        return url

    parsed = urlparse(url)

    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc
    path = parsed.path
    query = parsed.query

    # Preserve non-web schemes untouched: forcing "mailto:"/"javascript:" into
    # https produces garbage canonical URLs (e.g. the host is the whole payload).
    # urlparse misreads "example.com:80/foo" as scheme="example.com", so only
    # treat it as a foreign scheme when the remainder is not host:port shaped.
    if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
        looks_like_hostport = re.match(r"^\d{1,5}(/.*)?$", path) is not None
        if not looks_like_hostport:
            return url
        # Rebuild host:port from the misread pieces so the scheme-less path
        # below can process it normally.
        port_match = re.match(r"^(\d{1,5})(/?.*)$", path)
        port_part = port_match.group(1) if port_match else ""
        remainder = port_match.group(2) if port_match else ""
        netloc = f"{parsed.scheme}:{port_part}"
        scheme = "https"
        path = remainder or "/"

    # Handle scheme-less URLs like example.com/foo
    if not netloc and path:
        if "/" not in path:
            netloc = path
            path = "/"
        else:
            netloc, _, remainder = path.partition("/")
            path = f"/{remainder}" if remainder else "/"

    netloc = netloc.lower()

    host = _clean_host(netloc)

    # Normalize path, stripping AMP markers
    normalized_path = _normalize_path(path)
    previous_path = None
    while previous_path != normalized_path:
        previous_path = normalized_path
        for pattern in AMP_PATH_PATTERNS:
            normalized_path = pattern.sub("/", normalized_path)
    if not normalized_path:
        normalized_path = "/"

    # Parse and filter query parameters
    query_pairs = parse_qsl(query, keep_blank_values=False)
    filtered = list(_filter_query_params(query_pairs))
    filtered.sort(key=lambda item: (item[0], item[1]))
    normalized_query = "&".join(
        f"{key}={quote(value, safe='')}" if value else key for key, value in filtered
    )

    fragment = ""

    if scheme == "http":
        scheme = "https"

    # Remove default ports after scheme normalization.
    # Both 80 and 443 are default ports of the web schemes we consolidate to
    # https, so an explicit http://host:80/ or https://host:443/ loses nothing.
    if ":" in host:
        bare_host, port = host.rsplit(":", 1)
        if port in ("80", "443"):
            host = bare_host

    if not host:
        return url

    canonical = urlunparse(
        (scheme, host, normalized_path, "", normalized_query, fragment)
    )
    return canonical


_CACHE_SIZE = -1


def configure_canonicalization_cache(size: int) -> None:
    """Configure the LRU cache used by :func:`canonicalize_url`."""

    global canonicalize_url, _CACHE_SIZE
    if size == _CACHE_SIZE:
        return
    if size <= 0:
        canonicalize_url = _canonicalize_url_impl
    else:
        canonicalize_url = lru_cache(maxsize=size)(_canonicalize_url_impl)
    _CACHE_SIZE = size


def clear_canonicalization_cache() -> None:
    """Clear the active canonicalization cache if enabled."""

    if hasattr(canonicalize_url, "cache_clear"):
        canonicalize_url.cache_clear()


canonicalize_url: Callable[[str], str] = _canonicalize_url_impl


configure_canonicalization_cache(2048)


__all__ = [
    "canonicalize_url",
    "configure_canonicalization_cache",
    "clear_canonicalization_cache",
]
