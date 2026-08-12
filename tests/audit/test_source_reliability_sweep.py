"""
Real-network source reliability sweep — opt-in only.

Gated by NOTICIENCIAS_AUDIT=true. Fetches every source's RSS feed URL
and classifies each source into one of:

    WORKING       HTTP 200 + valid RSS/Atom XML + >= 1 entries
    TIMEOUT       No response within 30s
    HTTP_ERROR    Non-200 status (404, 410, 403, 503, etc.)
    MALFORMED     200 OK but feedparser bozo bit set
    EMPTY         Valid XML but 0 entries
    DNS_FAILURE   DNS resolution or connection refused
    SKIPPED       No RSS url or collector_type != rss

Usage:
    NOTICIENCIAS_AUDIT=true python -m pytest tests/audit/ -v -s
    NOTICIENCIAS_AUDIT=true python -m pytest tests/audit/ -v -s --sources phys_org openai_blog
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser
import httpx
import pytest

from news_collector.config import ALL_SOURCES

AUDIT_ENABLED = os.getenv("NOTICIENCIAS_AUDIT", "").lower() in {"true", "1", "yes"}
REQUEST_TIMEOUT = 30  # seconds per source
AUDIT_DIR = Path("data/audit")


# ── Classification ──────────────────────────────────────────────────────────


class SourceStatus:
    WORKING = "WORKING"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    MALFORMED = "MALFORMED"
    EMPTY = "EMPTY"
    DNS_FAILURE = "DNS_FAILURE"
    SKIPPED = "SKIPPED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class SourceResult:
    source_id: str
    name: str
    url: str
    status: str = SourceStatus.UNKNOWN_ERROR
    http_status: int = 0
    articles_found: int = 0
    latency: float = 0.0
    error_hint: str = ""
    feed_type: str = ""
    bozo: bool = False


# ── Helpers ─────────────────────────────────────────────────────────────────


ACCEPTABLE_BOZO_EXCEPTIONS = {
    "InvalidDocument",
    "UndeclaredNamespace",
    "SAXParseException",
}


def _is_acceptable_bozo(feed) -> bool:
    """Match the pipeline's RSS parser tolerance logic."""
    if not feed.bozo:
        return True
    exc = feed.get("bozo_exception")
    if exc is None:
        return False
    return exc.__class__.__name__ in ACCEPTABLE_BOZO_EXCEPTIONS


def _fetch_feed(url: str, source_config: Dict[str, Any]) -> tuple[int, str]:
    """Fetch a feed URL using httpx or curl_cffi based on source config."""
    if source_config.get("use_curl_cffi"):
        try:
            from scrapling import Fetcher

            page = Fetcher.get(
                url,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
            body = (
                page.body
                if isinstance(page.body, str)
                else page.body.decode("utf-8", errors="replace")
            )
            return getattr(page, "status", 200), body
        except Exception as e:
            raise RuntimeError(f"curl_cffi Error: {e}") from e

    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    return resp.status_code, resp.text


def _classify_source(
    source_id: str, name: str, url: str, source_config: Dict[str, Any]
) -> SourceResult:
    """Fetch the RSS feed URL and classify the source."""
    result = SourceResult(source_id=source_id, name=name, url=url)
    start = time.monotonic()

    try:
        status_code, body = _fetch_feed(url, source_config)
        result.latency = time.monotonic() - start
        result.http_status = status_code

        if status_code >= 400:
            result.status = SourceStatus.HTTP_ERROR
            result.error_hint = f"HTTP {status_code}"
            return result

        # Parse feed
        feed = feedparser.parse(body)
        result.bozo = bool(feed.get("bozo", 0))
        result.feed_type = feed.get("version", "unknown")

        if feed.bozo and not _is_acceptable_bozo(feed):
            result.status = SourceStatus.MALFORMED
            bozo_exc = feed.get("bozo_exception")
            result.error_hint = f"bozo: {bozo_exc}" if bozo_exc else "malformed XML"
            return result

        entries = feed.get("entries", [])
        result.articles_found = len(entries)

        if result.articles_found == 0:
            result.status = SourceStatus.EMPTY
            return result

        result.status = SourceStatus.WORKING

    except httpx.TimeoutException:
        result.latency = time.monotonic() - start
        result.status = SourceStatus.TIMEOUT
        result.error_hint = f"no response in {REQUEST_TIMEOUT}s"
    except httpx.ConnectError as e:
        result.latency = time.monotonic() - start
        result.status = SourceStatus.DNS_FAILURE
        result.error_hint = str(e).split(":")[-1].strip()[:60]
    except httpx.HTTPError as e:
        result.latency = time.monotonic() - start
        result.status = SourceStatus.HTTP_ERROR
        result.error_hint = str(e)[:60]
    except Exception as e:
        result.latency = time.monotonic() - start
        result.status = SourceStatus.UNKNOWN_ERROR
        result.error_hint = str(e)[:80]

    return result


def _get_rss_sources() -> Dict[str, Dict[str, Any]]:
    """Return only RSS/Atom sources (skip reddit, non-RSS)."""
    sources = {}
    for sid, cfg in ALL_SOURCES.items():
        collector = cfg.get("collector_type", "rss")
        if collector == "rss":
            sources[sid] = cfg
    return sources


def _render_summary_table(results: List[SourceResult]) -> str:
    """Render a monospace summary table."""
    lines = []
    lines.append("=" * 100)
    header = (
        f"{'source_id':<22} {'status':<18} {'HTTP':<6} "
        f"{'articles':<9} {'latency':<8} error_hint"
    )
    lines.append(header)
    lines.append("-" * 100)

    for r in sorted(results, key=lambda x: x.status):
        lat = f"{r.latency:.1f}s" if r.latency else "-"
        err = r.error_hint[:40] if r.error_hint else ""
        lines.append(
            f"{r.source_id:<22} {r.status:<18} {r.http_status:<6} "
            f"{r.articles_found:<9} {lat:<8} {err}"
        )
    lines.append("=" * 100)

    # Summary counts
    counts: Dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def _export_results(
    results: List[SourceResult],
    *,
    path: Optional[str] = None,
) -> str:
    """Export results as JSON and return the file path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if path is None:
        audit_dir = Path(AUDIT_DIR)
        audit_dir.mkdir(parents=True, exist_ok=True)
        path = str(audit_dir / f"source_reliability_{timestamp}.json")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(results),
        "results": [asdict(r) for r in results],
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


# ── Test ────────────────────────────────────────────────────────────────────


pytestmark = pytest.mark.skipif(
    not AUDIT_ENABLED,
    reason="Set NOTICIENCIAS_AUDIT=true to run real-network source reliability sweep",
)


def _get_filtered_sources(request: pytest.FixtureRequest) -> Dict[str, Dict[str, Any]]:
    """Support --sources CLI override via pytest's -k or custom marker."""
    marker = request.node.get_closest_marker("sources")
    if marker:
        return {sid: ALL_SOURCES[sid] for sid in marker.args if sid in ALL_SOURCES}
    return _get_rss_sources()


@pytest.mark.audit
@pytest.mark.timeout(3600)  # sweep can take 30min for 57 sources × 30s
def test_source_reliability_sweep(request: pytest.FixtureRequest):
    """Fetch every configured RSS source and classify its health."""
    sources = _get_rss_sources()
    total = len(sources)
    assert total > 0, "No RSS sources found in ALL_SOURCES"

    results: List[SourceResult] = []
    failures: List[SourceResult] = []

    print(f"\nFetching {total} RSS sources (timeout={REQUEST_TIMEOUT}s each)...")

    for i, (sid, cfg) in enumerate(sorted(sources.items()), 1):
        url = cfg.get("url", "")
        name = cfg.get("name", sid)
        print(f"  [{i:2d}/{total}] {sid:<22} ... ", end="", flush=True)

        result = _classify_source(sid, name, url, cfg)
        results.append(result)

        ok = "✓" if result.status == SourceStatus.WORKING else "✗"
        print(
            f"{ok} {result.status:<18} ({result.latency:.1f}s, {result.articles_found} articles)"
        )

        if result.status != SourceStatus.WORKING:
            failures.append(result)

    # Render summary
    table = _render_summary_table(results)
    print(f"\n{table}")

    # Export
    export_path = _export_results(results)
    print(f"\nResults exported to: {export_path}")

    # Only fail the test if NO sources work (informational, not blocking)
    working = sum(1 for r in results if r.status == SourceStatus.WORKING)
    if working == 0:
        pytest.fail(f"0/{total} sources working — pipeline is fully broken")
    else:
        print(f"\n{working}/{total} sources working. {len(failures)} non-working.")
