"""Focused tests for HTML collector health and reliability paths."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import news_collector.collectors.html_collector as html_module
from news_collector.collectors.html_collector import HtmlCollector


@pytest.fixture
def collector():
    instance = HtmlCollector(health_tracker=MagicMock())
    instance.db_manager = MagicMock()
    return instance


def _prepare_collect(monkeypatch, instance):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(html_module.asyncio, "to_thread", run_inline)
    monkeypatch.setattr(instance, "_make_job_key", lambda *_: "job")
    monkeypatch.setattr(instance, "_is_duplicate_job", lambda *_: False)
    monkeypatch.setattr(instance, "_register_job", lambda *_: None)
    monkeypatch.setattr(instance, "_respect_robots", lambda *_: (True, 0))
    monkeypatch.setattr(instance, "_enforce_domain_rate_limit", lambda *_: None)
    monkeypatch.setattr(instance, "_update_source_stats", lambda *_: None)
    monkeypatch.setattr(html_module, "validate_url_safety", lambda *_: None)


@pytest.mark.asyncio
async def test_empty_extraction_is_inconclusive_for_source_health(
    collector, monkeypatch
):
    _prepare_collect(monkeypatch, collector)
    collector._fetch_html_conditional = AsyncMock(return_value=("<html></html>", 200))
    collector._extract_articles_from_html = lambda *_: []

    result = await collector.collect_from_source_async(
        "html-empty", {"url": "https://example.test/news"}
    )

    assert result["success"] is True
    assert result["articles_found"] == 0
    collector.health_tracker.record_success.assert_called_once_with(
        "html-empty", "fetch"
    )
    collector.health_tracker.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_http_failure_is_recorded_as_fetch_failure(collector, monkeypatch):
    _prepare_collect(monkeypatch, collector)
    collector._fetch_html_conditional = AsyncMock(return_value=(None, 503))

    result = await collector.collect_from_source_async(
        "html-503", {"url": "https://example.test/news"}
    )

    assert result["success"] is False
    assert result["error_message"] == "Error HTTP 503"
    collector.health_tracker.record_failure.assert_called_once_with(
        "html-503", "collector.fetch", "HTTP 503", {"status_code": 503}
    )
    collector.health_tracker.record_success.assert_not_called()


@pytest.mark.asyncio
async def test_extraction_exception_is_observed_without_fake_parse_success(
    collector, monkeypatch
):
    _prepare_collect(monkeypatch, collector)
    collector._fetch_html_conditional = AsyncMock(return_value=("<html></html>", 200))

    def fail_extraction(*_args):
        raise ValueError("parser detail")

    collector._extract_articles_from_html = fail_extraction
    result = await collector.collect_from_source_async(
        "html-parse-error", {"url": "https://example.test/news"}
    )

    assert result["success"] is False
    collector.health_tracker.record_failure.assert_called_once_with(
        "html-parse-error", "collector.parse", "html_extraction_error"
    )
    collector.health_tracker.record_success.assert_not_called()


@pytest.mark.asyncio
async def test_missing_url_and_duplicate_job_return_without_fetch(
    collector, monkeypatch
):
    missing = await collector.collect_from_source_async("missing", {})
    assert missing["error_message"] == "URL no configurada"

    monkeypatch.setattr(collector, "_make_job_key", lambda *_: "duplicate")
    monkeypatch.setattr(collector, "_is_duplicate_job", lambda *_: True)
    duplicate = await collector.collect_from_source_async(
        "duplicate", {"url": "https://example.test/news"}
    )
    assert duplicate["success"] is True
    assert duplicate["articles_found"] == 0


@pytest.mark.asyncio
async def test_robots_denial_is_sent_to_dead_letter_queue(collector, monkeypatch):
    _prepare_collect(monkeypatch, collector)
    monkeypatch.setattr(collector, "_respect_robots", lambda *_: (False, 0))
    monkeypatch.setattr(collector, "_send_to_dlq", MagicMock())

    result = await collector.collect_from_source_async(
        "robots-denied", {"url": "https://example.test/news"}
    )

    assert result["success"] is False
    collector._send_to_dlq.assert_called_once_with(
        "robots-denied", "https://example.test/news", "robots_disallowed"
    )


def test_html_extraction_skips_bad_jsonld_and_uses_css_fallback(collector):
    html = """
    <script type="application/ld+json">{bad json</script>
    <script type="application/ld+json"></script>
    <script type="application/ld+json">{"@type":"WebPage"}</script>
    <div class="entry"><a href="/first">Fallback title</a></div>
    <div class="entry"><a>Missing href</a></div>
    <div class="entry"><a href="/empty"></a></div>
    """
    articles = collector._extract_articles_from_html(
        html,
        {"html_selectors": {"container": ".entry", "link": "a", "title": "h2"}},
        "source",
    )

    assert articles == [
        {
            "title": "Fallback title",
            "url": "/first",
            "description": "",
            "date": None,
        }
    ]


def test_blog_jsonld_uses_blogpost_when_item_list_is_empty(collector):
    articles = collector._extract_articles_from_html(
        '<script type="application/ld+json">'
        '{"@type":"Blog","itemListElement":[],"blogPost":'
        '[{"name":"Blog entry","url":"https://example.test/entry"}]}'
        "</script>",
        {},
        "source",
    )
    assert articles[0]["title"] == "Blog entry"


def test_process_article_html_validates_and_normalizes(collector):
    assert collector._process_article_html({"url": "/x"}, {}, "source") is None
    processed = collector._process_article_html(
        {
            "title": "A headline",
            "url": "/story",
            "description": "one two three",
        },
        {"url": "https://example.test/news", "category": "world"},
        "source",
    )
    assert processed is not None
    assert processed["url"] == "https://example.test/story"
    assert processed["source_id"] == "source"
    assert processed["word_count"] == 3
    assert processed["category"] == "world"
    assert isinstance(processed["published_date"], datetime)


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def get(self, url):
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_fetch_article_content_uses_main_and_filters_short_paragraphs(collector):
    response = httpx.Response(
        200,
        text="<main><p>This paragraph contains enough words to be retained.</p>"
        "<p>short</p></main>",
        request=httpx.Request("GET", "https://example.test/story"),
    )
    content = await collector._fetch_article_content(
        _FakeClient(response), "https://example.test/story", {}
    )
    assert content == "This paragraph contains enough words to be retained."

    not_found = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.test/missing"),
    )
    assert (
        await collector._fetch_article_content(
            _FakeClient(not_found), "https://example.test/missing", {}
        )
        is None
    )
    assert (
        await collector._fetch_article_content(
            _FakeClient(error=httpx.ConnectError("offline")),
            "https://example.test/offline",
            {},
        )
        is None
    )


def _response(status, body="", headers=None):
    return httpx.Response(
        status,
        text=body,
        headers=headers,
        request=httpx.Request("GET", "https://example.test/news"),
    )


def _client_with_results(*results):
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.get = AsyncMock(side_effect=list(results))
    return client


@pytest.mark.asyncio
async def test_conditional_html_fetch_retries_server_error(collector, monkeypatch):
    client = _client_with_results(_response(503), _response(200, "<html>ok</html>"))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(collector, "_backoff_sleep_async", AsyncMock())

    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )

    assert (content, status) == ("<html>ok</html>", 200)
    collector._backoff_sleep_async.assert_awaited_once_with(0)
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_conditional_html_fetch_records_rate_limit(collector, monkeypatch):
    retry_at = datetime(2026, 10, 9, tzinfo=timezone.utc)
    client = _client_with_results(_response(429, headers={"Retry-After": "30"}))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(collector, "_parse_retry_after", lambda *_: retry_at)

    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )

    assert (content, status) == (None, 429)
    collector.db_manager.update_source_circuit_state.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limit_without_retry_after_uses_default_cooldown(
    collector, monkeypatch
):
    client = _client_with_results(_response(429))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(collector, "_parse_retry_after", lambda *_: None)

    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )

    assert (content, status) == (None, 429)
    kwargs = collector.db_manager.update_source_circuit_state.call_args.kwargs
    assert (
        kwargs["force_cooldown_until"] - datetime.now(timezone.utc)
    ).total_seconds() > 14 * 60


@pytest.mark.asyncio
async def test_conditional_html_fetch_retries_timeout_and_returns_client_error(
    collector, monkeypatch
):
    client = _client_with_results(
        httpx.TimeoutException("timeout"), _response(200, "<html>ok</html>")
    )
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(collector, "_backoff_sleep_async", AsyncMock())
    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )
    assert (content, status) == ("<html>ok</html>", 200)
    assert client.get.await_count == 2

    client = _client_with_results(_response(404))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )
    assert (content, status) == (None, 404)
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_conditional_fetch_handles_exhausted_retries_and_unchanged_content(
    collector, monkeypatch
):
    client = _client_with_results(_response(503), _response(503), _response(503))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(collector, "_backoff_sleep_async", AsyncMock())
    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )
    assert (content, status) == (None, 503)
    assert client.get.await_count == 3

    body = "unchanged page"
    collector.db_manager.get_source_feed_metadata.return_value = {
        "content_hash": html_module.hashlib.sha256(body.encode()).hexdigest()
    }
    client = _client_with_results(_response(200, body))
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    content, status = await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    )
    assert (content, status) == (None, 304)


@pytest.mark.asyncio
async def test_conditional_fetch_returns_after_all_network_retries(
    collector, monkeypatch
):
    client = _client_with_results(
        httpx.TimeoutException("timeout"),
        httpx.TimeoutException("timeout"),
        httpx.TimeoutException("timeout"),
    )
    monkeypatch.setattr(html_module.httpx, "AsyncClient", lambda **_: client)
    backoff = AsyncMock()
    monkeypatch.setattr(collector, "_backoff_sleep_async", backoff)

    assert await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    ) == (None, None)
    assert client.get.await_count == 3
    assert backoff.await_count == 2


@pytest.mark.asyncio
async def test_conditional_fetch_observes_unexpected_client_setup_failure(
    collector, monkeypatch
):
    monkeypatch.setattr(
        html_module.httpx,
        "AsyncClient",
        lambda **_: (_ for _ in ()).throw(RuntimeError("client setup failed")),
    )
    emit = MagicMock()
    monkeypatch.setattr(collector, "_emit_log", emit)

    assert await collector._fetch_html_conditional(
        "https://example.test/news", "source", {}
    ) == (None, None)
    emit.assert_called_once()
