"""Plan 120 Step 4: HTML-collector control-path coverage.

The coverage ratchet requires >=90% line / >=70% branch coverage for every
touched module; ``html_collector.py`` sat at ~80% line. These tests lock in
the early-exit, fallback, and retry branches (sync wrapper, robots,
duplicate jobs, parse failures, JSON-LD/CSS extraction edges, conditional
fetch outcomes) with mocked HTTP — no network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from news_collector.collectors.html_collector import HtmlCollector

LIST_HTML = """
<html><body>
<article><a href="/article/1"><h2>List Article One</h2></a></article>
</body></html>
"""
DETAIL_HTML = """
<html><body><article><p>This is the full article body text for testing.</p></article></body></html>
"""


@pytest.fixture
def collector():
    with patch("news_collector.collectors.html_collector.get_runtime_config"):
        return HtmlCollector(logger_factory=MagicMock())


@pytest.fixture
def tracked_collector():
    with patch("news_collector.collectors.html_collector.get_runtime_config"):
        return HtmlCollector(logger_factory=MagicMock(), health_tracker=MagicMock())


def _config(**overrides):
    cfg = {"url": "https://example.com/news", "name": "Test Source"}
    cfg.update(overrides)
    return cfg


def _client_mock(*responses, get_side_effect=None):
    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False
    if get_side_effect is not None:
        mock_client.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock_client.get = AsyncMock(side_effect=list(responses))
    return mock_client


# --- collect_from_source_async early exits -------------------------------- #


def test_sync_wrapper_delegates(collector):
    sentinel = {"success": True, "source_id": "s"}
    with patch.object(
        collector,
        "collect_from_source_async",
        new=AsyncMock(return_value=sentinel),
    ):
        assert collector.collect_from_source("s", {}) == sentinel


@pytest.mark.asyncio
async def test_missing_url_early_exit(tracked_collector):
    stats = await tracked_collector.collect_from_source_async("s", {"name": "N"})
    assert stats["success"] is False
    assert stats["error_message"] == "URL no configurada"
    tracked_collector.health_tracker.record_attempt.assert_called_once_with("s")


@pytest.mark.asyncio
async def test_duplicate_job_short_circuits(collector):
    with patch.object(collector, "_is_duplicate_job", return_value=True):
        stats = await collector.collect_from_source_async("s", _config())
    assert stats["success"] is True
    assert stats["articles_found"] == 0


@pytest.mark.asyncio
async def test_robots_disallowed_sends_dlq(collector):
    with patch.object(collector, "_respect_robots", return_value=(False, 0.5)):
        with patch.object(collector, "_send_to_dlq") as dlq:
            stats = await collector.collect_from_source_async("s", _config())
    assert stats["success"] is False
    assert stats["error_message"] == "Bloqueado por robots.txt"
    dlq.assert_called_once()


@pytest.mark.asyncio
async def test_parse_exception_recorded(collector):
    client = _client_mock(httpx.Response(200, text=LIST_HTML))
    with patch.object(collector, "_respect_robots", return_value=(True, 0)):
        with patch("news_collector.collectors.html_collector.validate_url_safety"):
            with patch("httpx.AsyncClient", return_value=client):
                with patch.object(
                    collector,
                    "_extract_articles_from_html",
                    side_effect=RuntimeError("boom"),
                ):
                    with patch.object(collector, "_update_source_stats"):
                        stats = await collector.collect_from_source_async(
                            "s", _config()
                        )
    assert stats["success"] is False
    assert "Error de parsing" in stats["error_message"]


@pytest.mark.asyncio
async def test_unexpected_exception_path(collector):
    with patch.object(collector, "_respect_robots", side_effect=RuntimeError("boom")):
        with patch.object(collector, "_update_source_stats"):
            stats = await collector.collect_from_source_async("s", _config())
    assert stats["success"] is False
    assert "Excepción inesperada" in stats["error_message"]


@pytest.mark.asyncio
async def test_happy_path_with_health_tracker(tracked_collector):
    client = _client_mock(
        httpx.Response(200, text=LIST_HTML),
        httpx.Response(200, text=DETAIL_HTML),
    )
    with patch.object(tracked_collector, "_respect_robots", return_value=(True, 0)):
        with patch("news_collector.collectors.html_collector.validate_url_safety"):
            with patch("httpx.AsyncClient", return_value=client):
                with patch.object(tracked_collector, "_enforce_domain_rate_limit"):
                    with patch.object(
                        tracked_collector,
                        "_filter_and_save_articles",
                        return_value=1,
                    ) as save:
                        with patch.object(tracked_collector, "_update_source_stats"):
                            stats = await tracked_collector.collect_from_source_async(
                                "s", _config()
                            )
    assert stats["success"] is True
    assert stats["articles_found"] == 1
    assert save.call_count == 1
    tracked_collector.health_tracker.record_success.assert_any_call("s", "fetch")


# --- extraction edges ------------------------------------------------------ #


def test_json_ld_empty_payload_skipped(collector):
    html = (
        '<html><head><script type="application/ld+json"></script></head>'
        '<body><article><a href="/x"><h2>Fallback Title Here</h2></a></article>'
        "</body></html>"
    )
    articles = collector._extract_articles_from_html(html, {}, "s")
    assert len(articles) == 1
    assert articles[0]["title"] == "Fallback Title Here"


def test_json_ld_invalid_json_skipped(collector):
    html = (
        '<html><head><script type="application/ld+json">{not json</script></head>'
        "<body></body></html>"
    )
    assert collector._extract_articles_from_html(html, {}, "s") == []


def test_json_ld_blog_shape_skips_non_dict_items(collector):
    html = """
    <html><head><script type="application/ld+json">
    {"@type": "Blog", "blogPost": [
        "not-a-dict",
        {"headline": "Blog Post Title Here", "url": "https://example.com/b1"}
    ]}
    </script></head><body></body></html>
    """
    articles = collector._extract_articles_from_html(html, {}, "s")
    assert len(articles) == 1
    assert articles[0]["title"] == "Blog Post Title Here"


def test_css_container_without_link_skipped(collector):
    html = '<html><body><div class="news-item"><span>No link here</span></div></body></html>'
    config = {"html_selectors": {"container": "div.news-item"}}
    assert collector._extract_articles_from_html(html, config, "s") == []


def test_css_title_falls_back_to_link_text(collector):
    html = '<html><body><article><a href="/y">Link Text Title Here</a></article></body></html>'
    config = {"html_selectors": {"title": "h99-missing"}}
    articles = collector._extract_articles_from_html(html, config, "s")
    assert len(articles) == 1
    assert articles[0]["title"] == "Link Text Title Here"


def test_css_container_exception_skipped(collector):
    bad_container = MagicMock()
    bad_container.select_one.side_effect = AttributeError("boom")
    fake_soup = MagicMock()
    fake_soup.find_all.return_value = []
    fake_soup.select.return_value = [bad_container]
    with patch(
        "news_collector.collectors.html_collector.BeautifulSoup",
        return_value=fake_soup,
    ):
        assert collector._extract_articles_from_html("<html></html>", {}, "s") == []


def test_process_returns_none_without_url_or_title(collector):
    assert collector._process_article_html({}, _config(), "s") is None
    assert (
        collector._process_article_html(
            {"url": "https://example.com/x"}, _config(), "s"
        )
        is None
    )


def test_parse_json_ld_article_defaults(collector):
    art = collector._parse_json_ld_article({})
    assert art["title"] == ""
    assert art["date"] == ""


# --- _fetch_article_content branches --------------------------------------- #


@pytest.mark.asyncio
async def test_fetch_content_http_error_returns_none(collector):
    client = _client_mock(httpx.Response(404, text="missing"))
    assert (
        await collector._fetch_article_content(client, "https://example.com/x", {})
        is None
    )


@pytest.mark.asyncio
async def test_fetch_content_configured_selector(collector):
    html = '<html><body><div class="body"><p>This paragraph is long enough to keep here.</p></div></body></html>'
    client = _client_mock(httpx.Response(200, text=html))
    text = await collector._fetch_article_content(
        client,
        "https://example.com/x",
        {"html_selectors": {"article_selector": "div.body"}},
    )
    assert text is not None and "long enough" in text


@pytest.mark.asyncio
async def test_fetch_content_no_container_returns_none(collector):
    client = _client_mock(httpx.Response(200, text=""))
    assert (
        await collector._fetch_article_content(client, "https://example.com/x", {})
        is None
    )


@pytest.mark.asyncio
async def test_fetch_content_exception_returns_none(collector):
    client = _client_mock(get_side_effect=RuntimeError("network down"))
    assert (
        await collector._fetch_article_content(client, "https://example.com/x", {})
        is None
    )


# --- _fetch_html_conditional outcomes -------------------------------------- #


def _conditional_collector(collector):
    collector.db_manager = MagicMock()
    collector.db_manager.get_source_feed_metadata.return_value = None
    return collector


@pytest.mark.asyncio
async def test_conditional_fetch_304(collector):
    _conditional_collector(collector)
    resp = httpx.Response(304, headers={"ETag": '"abc"'})
    client = _client_mock(resp)
    with patch("httpx.AsyncClient", return_value=client):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news", "s", _config()
        )
    assert (content, status) == (None, 304)
    collector.db_manager.update_source_feed_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_conditional_fetch_429_without_retry_after_uses_default(collector):
    _conditional_collector(collector)
    client = _client_mock(httpx.Response(429))
    with patch("httpx.AsyncClient", return_value=client):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news", "s", _config()
        )
    assert (content, status) == (None, 429)
    collector.db_manager.update_source_circuit_state.assert_called_once()


@pytest.mark.asyncio
async def test_conditional_fetch_500_then_gives_up(collector):
    _conditional_collector(collector)
    client = _client_mock(
        httpx.Response(500, text="err"),
        httpx.Response(500, text="err"),
        httpx.Response(500, text="err"),
    )
    with patch("httpx.AsyncClient", return_value=client):
        with patch.object(collector, "_backoff_sleep_async", new=AsyncMock()):
            content, status = await collector._fetch_html_conditional(
                "https://example.com/news", "s", _config()
            )
    assert (content, status) == (None, 500)


@pytest.mark.asyncio
async def test_conditional_fetch_timeout_retries_exhausted(collector):
    _conditional_collector(collector)
    client = _client_mock(get_side_effect=httpx.TimeoutException("slow"))
    with patch("httpx.AsyncClient", return_value=client):
        with patch.object(collector, "_backoff_sleep_async", new=AsyncMock()):
            content, status = await collector._fetch_html_conditional(
                "https://example.com/news", "s", _config()
            )
    assert (content, status) == (None, None)


@pytest.mark.asyncio
async def test_conditional_fetch_outer_exception(collector):
    _conditional_collector(collector)
    with patch("httpx.AsyncClient", side_effect=RuntimeError("client boom")):
        content, status = await collector._fetch_html_conditional(
            "https://example.com/news", "s", _config()
        )
    assert (content, status) == (None, None)
