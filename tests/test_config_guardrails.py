from pathlib import Path

import pytest
import yaml
from news_collector.config.settings import BASE_DIR


def test_source_urls_are_rss():
    """
    Regression test: Ensure no sources are pointing to HTML pages unless strictly allowed.
    This prevents 'headless' scrapes from creeping back in disguise.
    """
    sources_path = BASE_DIR / "news_collector" / "config" / "sources.yaml"
    if not sources_path.exists():
        # Try alternative path relative to root if running from root
        sources_path = Path("news_collector/config/sources.yaml")

    with open(sources_path, "r") as f:
        sources = yaml.safe_load(f)

    # Block list of known HTML-only patterns that we replaced
    html_patterns = ["/latest", "/news", "/current", "/toc/", "/home/", "/research"]

    # Allow list for legitimate URL components (e.g. if the RSS feed URL happens to have 'news' in it)
    # But it must ALSO look like a feed.

    for source_id, config in sources.items():
        if not config.get("is_active", True):
            continue

        url = config["url"]
        lower_url = url.lower()

        # 1. Check for specific replaced endpoints (Strong Signal)
        if "nature.com/latest-news" in url:
            pytest.fail(f"Source {source_id} configured with HTML endpoint: {url}")
        if "science.org/news" in url and "rss" not in lower_url:
            pytest.fail(f"Source {source_id} configured with HTML endpoint: {url}")

        # 2. Heuristic: Must look like RSS/Atom or have explicit metadata
        looks_like_feed = any(
            x in lower_url for x in ["rss", "feed", "xml", "atom", "json"]
        )

        # If it doesn't look like a feed, check if it looks suspiciously like a web page
        if not looks_like_feed:
            if any(url.endswith(bad) for bad in html_patterns):
                pytest.fail(
                    f"Source {source_id} URL looks like a web page, not a feed: {url}"
                )

            # If it's just a clean URL (e.g. phys.org/), it's suspicious for an RSS collector
            if config.get("collector_type", "rss") == "rss" and url.count("/") < 4:
                # Some root URLs serve RSS? Rare.
                # Warn or fail?
                # Let's check for slash-only ending
                pytest.fail(
                    f"Source {source_id} URL seems to be a root domain (HTML): {url}"
                )
