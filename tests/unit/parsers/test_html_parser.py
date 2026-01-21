
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from news_collector.collectors.html_collector import HtmlCollector
from news_collector.contracts import CollectorArticleModel

@pytest.fixture
def html_collector():
    return HtmlCollector()

@pytest.mark.asyncio
async def test_html_collector_extracts_with_article_selector(html_collector):
    """
    Verifies that _fetch_article_content uses the configured article_selector
    to isolate content, as implemented for deepmind_blog.
    """
    html_content = """
    <html>
        <body>
            <div class="sidebar">Ignore me</div>
            <article class="main-article">
                <p>This is the important content.</p>
                <p>It should be extracted.</p>
            </article>
            <div class="footer">Ignore me too</div>
        </body>
    </html>
    """
    
    config = {
        "html_selectors": {
            "article_selector": "article.main-article"
        }
    }
    
    # Mock the response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html_content
    
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    
    url = "https://example.com/article"
    
    content = await html_collector._fetch_article_content(mock_client, url, config)
    
    assert content is not None
    assert "This is the important content" in content
    assert "It should be extracted" in content
    assert "Ignore me" not in content

@pytest.mark.asyncio
async def test_html_collector_fallback_heuristics(html_collector):
    """Verifies fallback to <article> tag if no selector configured."""
    html_content = """
    <html>
        <body>
            <article>
                <p>Fallback content must be longer than twenty characters to pass the filter logic.</p>
            </article>
        </body>
    </html>
    """
    # Empty config
    config = {}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html_content
    
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    
    content = await html_collector._fetch_article_content(mock_client, "http://url", config)
    assert content is not None
    assert "Fallback content" in content
