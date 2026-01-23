import asyncio
from unittest.mock import MagicMock, patch

import pytest

from news_collector.collectors.html_collector import HtmlCollector


@pytest.fixture
def html_collector():
    return HtmlCollector()


@pytest.mark.asyncio
async def test_html_collector_json_ld_extraction(html_collector):
    """Verifies extraction via JSON-LD."""
    html = """
    <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "NewsArticle",
                        "headline": "JSON-LD Article",
                        "url": "https://example.com/json-ld",
                        "description": "Description from JSON-LD"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
    </html>
    """
    articles = await asyncio.to_thread(
        html_collector._extract_articles_from_html, html, {}, "test_source"
    )
    assert len(articles) == 1
    assert articles[0]["title"] == "JSON-LD Article"
    assert articles[0]["url"] == "https://example.com/json-ld"


@pytest.mark.asyncio
async def test_html_collector_css_selector_extraction(html_collector):
    """Verifies extraction via CSS selectors."""
    html = """
    <html>
        <body>
            <div class="news-item">
                <a href="/news/1"><h3>Article 1</h3></a>
            </div>
            <div class="news-item">
                <a href="/news/2"><h3>Article 2</h3></a>
            </div>
        </body>
    </html>
    """
    config = {
        "html_selectors": {"container": "div.news-item", "link": "a", "title": "h3"}
    }

    articles = await asyncio.to_thread(
        html_collector._extract_articles_from_html, html, config, "test_source"
    )
    assert len(articles) == 2
    assert articles[0]["title"] == "Article 1"
    assert (
        articles[0]["url"] == "/news/1"
    )  # Will be normalized in _process_article_html
    assert articles[1]["title"] == "Article 2"


@pytest.mark.asyncio
async def test_collect_from_source_full_flow(html_collector):
    """Verifies full async collection flow with mocked HTTP."""
    html_list = """
    <html>
        <body>
            <article>
                <a href="/article/full"><h2>Full Flow Article</h2></a>
            </article>
        </body>
    </html>
    """
    html_detail = """
    <html>
        <body>
            <article>
                <p>This is the full content of the article needed for validation.</p>
            </article>
        </body>
    </html>
    """

    import httpx

    mock_client = MagicMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mock_list_resp = httpx.Response(200, text=html_list)
    mock_detail_resp = httpx.Response(200, text=html_detail)

    # Define async side effect
    responses = iter([mock_list_resp, mock_detail_resp])

    async def side_effect(*args, **kwargs):
        return next(responses)

    mock_client.get.side_effect = side_effect

    # Patch httpx.AsyncClient to return our mock
    # Note: httpx.AsyncClient() returns the client instance (mock_client)
    # Then 'async with' calls __aenter__
    with patch("httpx.AsyncClient", return_value=mock_client):
        # Patch robots/safety to avoid obstacles
        with patch.object(html_collector, "_respect_robots", return_value=(True, 0)):
            with patch("news_collector.collectors.html_collector.validate_url_safety"):
                # Patch save to avoid DB
                with patch.object(
                    html_collector, "_filter_and_save_articles", return_value=1
                ):
                    # Patch rate limiter to prevent sleep
                    with patch.object(html_collector, "_enforce_domain_rate_limit"):

                        stats = await html_collector.collect_from_source_async(
                            "test_source",
                            {
                                "url": "https://example.com/news",
                                "html_selectors": {"container": "article"},
                            },
                        )

                        assert (
                            stats["success"] is True
                        ), f"Collection failed: {stats.get('error_message')}"
                        assert stats["articles_found"] == 1
                        assert stats["articles_saved"] == 1

                        # Verify detail fetch happened
                        assert mock_client.get.call_count == 2
