import pytest
from news_collector.collectors import RSSCollector


def test_ssrf_protection_blocks_internal_ips(monkeypatch):
    """
    Test that the RSSCollector blocks requests to internal/private IP addresses
    to prevent SSRF attacks.
    """
    collector = RSSCollector()

    # Mock _respect_robots avoiding network calls
    monkeypatch.setattr(RSSCollector, "_respect_robots", lambda self, url: (True, None))
    monkeypatch.setattr(RSSCollector, "_enforce_domain_rate_limit", lambda *args: None)

    # Internal URL examples
    internal_urls = [
        "http://localhost:8080/feed",
        "http://127.0.0.1:8000/metrics",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0:5000",
        "http://[::1]/secret",
    ]

    for url in internal_urls:
        source_config = {"name": "Internal Service", "url": url, "category": "test"}

        # We expect a failure due to SSRF protection (once implemented)
        # OR we can inspect the logs/return stats

        # Mock requests.Session.get to raise if it actually tries to connect
        # (This confirms vulnerability if it tries, or confirms fix if we block before)

        # ACTUALLY, for the fix verification, we want to see that our *custom SSRF check*
        # stops it before requests.get is even called, or that requests.get is configured safely.

        # For now, let's spy on _fetch_feed

        collector.collect_from_source("ssrf_test", source_config)

        # If vulnerable, it might try to connect and fail with ConnectionError
        # If protected, it should fail with "Blocked by SSRF protection" logic we will add.

        # Current vulnerable behavior:
        # It tries to fetch, likely gets ConnectionError (since no service is there)
        # but the request ATTEMPT is made.

        # Desired behavior:
        # The request is NOT made to the network layer for these IPs.

        pass

    # A more specific test for the implementation we plan:
    # assessing `_validate_url_safety` method that we will add.

    with pytest.raises(ValueError, match="SSRF"):
        # We will expose/test the validator directly or via a specific hook
        from news_collector.collectors.rss_collector import validate_url_safety

        validate_url_safety("http://169.254.169.254")
