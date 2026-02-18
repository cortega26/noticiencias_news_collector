from unittest.mock import MagicMock

import pytest
from news_collector.logic.parsers.image_extractor import ImageCandidate, ImageExtractor


@pytest.fixture
def image_extractor():
    session = MagicMock()
    return ImageExtractor(session=session)


def test_extract_candidates_metadata(image_extractor):
    html = """
    <html>
        <head>
            <meta property="og:image" content="https://example.com/og_image.jpg" />
            <meta name="twitter:image" content="https://example.com/tw_image.jpg" />
        </head>
        <body></body>
    </html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/article")
    assert len(candidates) == 2
    assert candidates[0].url == "https://example.com/og_image.jpg"
    assert candidates[0].source == "meta:og:image"


def test_extract_candidates_dom(image_extractor):
    html = """
    <html>
        <body>
            <article>
                <img src="/images/article_image.jpg" width="800" height="600" />
                <img src="icon.png" class="logo" />
            </article>
        </body>
    </html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/article")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/images/article_image.jpg"
    assert candidates[0].source == "dom"
    assert candidates[0].score > 1.0  # Should get boost for size


def test_extract_candidates_lazy(image_extractor):
    html = """
    <html>
        <body>
            <article>
                <img data-src="https://example.com/lazy.jpg" />
            </article>
        </body>
    </html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/lazy.jpg"


def test_blacklist(image_extractor):
    html = """
    <html>
        <body>
            <img src="https://example.com/logo.png" />
            <img src="https://example.com/tracker.gif" />
            <img src="https://example.com/valid.jpg" />
        </body>
    </html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com")
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/valid.jpg"


def test_validation_success(image_extractor):
    candidate = ImageCandidate(url="https://example.com/img.jpg", source="dom")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/jpeg", "Content-Length": "10000"}
    image_extractor.session.head.return_value = mock_resp

    assert image_extractor.validate_image(candidate) is True


def test_validation_reject_small(image_extractor):
    candidate = ImageCandidate(url="https://example.com/tiny.jpg", source="dom")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/jpeg", "Content-Length": "100"}
    image_extractor.session.head.return_value = mock_resp

    assert image_extractor.validate_image(candidate) is False
