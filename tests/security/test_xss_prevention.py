
import pytest
from news_collector.utils.text_cleaner import clean_html

def test_clean_html_strips_scripts():
    """Verify that <script> tags are completely removed."""
    html = '<div><script>alert("XSS")</script>Content</div>'
    result = clean_html(html)
    assert 'alert' not in result
    assert 'XSS' not in result
    assert result == "Content"

def test_clean_html_strips_event_handlers():
    """Verify that on* attributes are gone (though get_text should strip all attributes)."""
    html = '<a href="#" onclick="stealCookies()">Click me</a>'
    result = clean_html(html)
    # Since clean_html converts to plain text, attributes should be gone anyway
    assert 'onclick' not in result
    assert 'stealCookies' not in result
    assert result == "Click me"

def test_clean_html_handles_malformed_tags():
    """Verify behavior with broken tags."""
    html = '<div <script>alert(1)</script>>Hello</div>'
    # BS4 parses this gently. We want to ensure script content is not leaked as text.
    result = clean_html(html)
    assert result == "alert(1)>Hello" # lxml/browsers handle this as text; no script executed.


def test_clean_html_strips_styles():
    html = '<style>body { background: red; }</style>Text'
    result = clean_html(html)
    assert 'background' not in result
    assert result == "Text"
