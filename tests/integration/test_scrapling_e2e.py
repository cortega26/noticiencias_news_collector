"""
E2E integration test for Scrapling StealthyFetcher against hard-to-scrape sources.

Opt-in only — requires SCRAPLING_E2E=true and ENABLE_HEADLESS=true.
Run with:
    SCRAPLING_E2E=true ENABLE_HEADLESS=true pytest tests/integration/test_scrapling_e2e.py -v -s

This test:
1. Fetches each hard source with plain httpx (baseline).
2. Fetches the same source with StealthyFetcher (Scrapling).
3. Reports success, status codes, and content lengths for comparison.

It does NOT assert on specific content — only that the pipeline can reach the site.
Success threshold: scrapling_success_rate >= httpx_success_rate.
"""

import os
import time
from dataclasses import dataclass, field
from typing import List

import pytest

SCRAPLING_E2E = os.getenv("SCRAPLING_E2E", "false").lower() == "true"

# Hard sources confirmed to need headless/stealth in the pipeline
HARD_SOURCES = [
    {"id": "phys_org", "url": "https://phys.org/", "min_content_chars": 500},
    {
        "id": "sciencedaily_top",
        "url": "https://www.sciencedaily.com/",
        "min_content_chars": 500,
    },
    {
        "id": "deepmind_blog",
        "url": "https://deepmind.google/blog/",
        "min_content_chars": 500,
    },
    {
        "id": "harvard_gazette",
        "url": "https://news.harvard.edu/gazette/",
        "min_content_chars": 500,
    },
    {
        "id": "uw_news",
        "url": "https://www.washington.edu/news/",
        "min_content_chars": 500,
    },
    {
        "id": "uw_madison_news",
        "url": "https://news.wisc.edu/",
        "min_content_chars": 500,
    },
    {
        "id": "microsoft_research",
        "url": "https://www.microsoft.com/en-us/research/blog/",
        "min_content_chars": 500,
    },
]

TIMEOUT_SECONDS = 30


@dataclass
class FetchResult:
    source_id: str
    url: str
    method: str
    success: bool
    status_code: int = 0
    content_length: int = 0
    duration: float = 0.0
    error: str = ""


def _fetch_with_httpx(source_id: str, url: str) -> FetchResult:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    start = time.time()
    try:
        r = httpx.get(
            url, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True
        )
        return FetchResult(
            source_id=source_id,
            url=url,
            method="httpx",
            success=r.status_code < 400,
            status_code=r.status_code,
            content_length=len(r.text),
            duration=time.time() - start,
        )
    except Exception as e:
        return FetchResult(
            source_id=source_id,
            url=url,
            method="httpx",
            success=False,
            duration=time.time() - start,
            error=str(e),
        )


def _fetch_with_scrapling(source_id: str, url: str) -> FetchResult:
    from scrapling.fetchers import StealthyFetcher

    start = time.time()
    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            solve_cloudflare=True,
            block_webrtc=True,
            hide_canvas=True,
            network_idle=True,
            timeout=TIMEOUT_SECONDS * 1000,
            disable_resources=True,
        )
        text = page.get_all_text(separator=" ", strip=True)
        content = " ".join(str(text).split())
        return FetchResult(
            source_id=source_id,
            url=url,
            method="scrapling",
            success=page.status < 400 and len(content) >= 100,
            status_code=page.status,
            content_length=len(content),
            duration=time.time() - start,
        )
    except Exception as e:
        return FetchResult(
            source_id=source_id,
            url=url,
            method="scrapling",
            success=False,
            duration=time.time() - start,
            error=str(e),
        )


def _print_results_table(results: List[FetchResult]) -> None:
    print("\n" + "=" * 90)
    print(
        f"{'Source':<22} {'Method':<12} {'OK':<5} {'Status':<8} {'Chars':<10} {'Time(s)':<8} {'Error'}"
    )
    print("-" * 90)
    for r in results:
        ok = "✓" if r.success else "✗"
        err = r.error[:35] if r.error else ""
        print(
            f"{r.source_id:<22} {r.method:<12} {ok:<5} {r.status_code:<8} {r.content_length:<10} {r.duration:<8.1f} {err}"
        )
    print("=" * 90)


@pytest.mark.skipif(
    not SCRAPLING_E2E, reason="Set SCRAPLING_E2E=true to run real network tests"
)
@pytest.mark.timeout(600)
def test_scrapling_improves_hard_source_fetch_rate():
    """
    Compares httpx vs Scrapling StealthyFetcher for the 7 hard-to-scrape sources.
    Asserts scrapling_success_rate >= httpx_success_rate (Scrapling must not regress).
    """
    httpx_results: List[FetchResult] = []
    scrapling_results: List[FetchResult] = []

    for source in HARD_SOURCES:
        print(f"\n→ Testing {source['id']} ...")

        httpx_r = _fetch_with_httpx(source["id"], source["url"])
        httpx_results.append(httpx_r)
        print(
            f"  httpx:     {'OK' if httpx_r.success else 'FAIL'} [{httpx_r.status_code}] {httpx_r.content_length} chars ({httpx_r.duration:.1f}s)"
        )

        scrapling_r = _fetch_with_scrapling(source["id"], source["url"])
        scrapling_results.append(scrapling_r)
        print(
            f"  scrapling: {'OK' if scrapling_r.success else 'FAIL'} [{scrapling_r.status_code}] {scrapling_r.content_length} chars ({scrapling_r.duration:.1f}s)"
        )

    _print_results_table(httpx_results + scrapling_results)

    httpx_ok = sum(1 for r in httpx_results if r.success)
    scrapling_ok = sum(1 for r in scrapling_results if r.success)
    total = len(HARD_SOURCES)

    httpx_rate = httpx_ok / total
    scrapling_rate = scrapling_ok / total

    print(
        f"\nSummary: httpx {httpx_ok}/{total} ({httpx_rate:.0%})  scrapling {scrapling_ok}/{total} ({scrapling_rate:.0%})"
    )

    # Scrapling must not be worse than plain httpx
    assert scrapling_rate >= httpx_rate, (
        f"Scrapling success rate {scrapling_rate:.0%} is LOWER than httpx {httpx_rate:.0%}. "
        "Check StealthyFetcher configuration."
    )

    # At least 2 sources must succeed with scrapling to confirm it's working
    assert scrapling_ok >= 2, (
        f"Only {scrapling_ok}/{total} sources succeeded with Scrapling. "
        "Check if `scrapling install` was run and ENABLE_HEADLESS=true is set."
    )
