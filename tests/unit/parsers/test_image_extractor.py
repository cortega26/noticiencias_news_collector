import html as html_lib
import random
from unittest.mock import MagicMock

import pytest

from news_collector.editorial.hero_alt import is_boilerplate_alt
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


def test_metadata_og_and_twitter_alts_attached(image_extractor):
    html = """
    <html><head>
        <meta property="og:image" content="https://example.com/og.jpg" />
        <meta property="og:image:alt" content="Un laboratorio con microscopios." />
        <meta name="twitter:image" content="https://example.com/tw.jpg" />
        <meta name="twitter:image:alt" content="Investigadores trabajando de noche." />
    </head><body></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")
    by_source = {c.source: c for c in candidates}

    assert by_source["meta:og:image"].alt == "Un laboratorio con microscopios."
    assert by_source["meta:twitter:image"].alt == "Investigadores trabajando de noche."


def test_og_alt_never_misapplied_to_twitter_candidate(image_extractor):
    html = """
    <html><head>
        <meta property="og:image:alt" content="Descripción de la imagen principal." />
        <meta name="twitter:image" content="https://example.com/tw.jpg" />
    </head><body></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")

    assert candidates and candidates[0].alt is None


def test_dom_img_alt_attached(image_extractor):
    html = """
    <html><body><article>
        <img src="/images/a.jpg" width="800" height="600"
             alt="Una ballena saltando frente a la costa." />
    </article></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")

    assert len(candidates) == 1
    assert candidates[0].alt == "Una ballena saltando frente a la costa."


def test_dom_figcaption_used_when_img_alt_missing(image_extractor):
    html = """
    <html><body><article>
        <figure>
            <img src="/images/a.jpg" width="800" height="600" />
            <figcaption>  Restos   del naufragio
            hallados en la costa. </figcaption>
        </figure>
    </article></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")

    assert candidates[0].alt == "Restos del naufragio hallados en la costa."


@pytest.mark.parametrize(
    "bad_alt",
    [
        "",
        "   ",
        "abc",
        "Imagen de un laboratorio",
        "ilustración editorial relacionada con Titular",
    ],
)
def test_unusable_source_alt_rejected(image_extractor, bad_alt):
    html = f"""
    <html><body><article>
        <img src="/images/a.jpg" width="800" height="600" alt="{bad_alt}" />
    </article></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")

    assert candidates[0].alt is None


def test_alt_invariants_under_generated_inputs(image_extractor):
    rng = random.Random(20260929)
    alphabet = "abc áéíóúñ 0123456789 <>&\"'\\\n\t“”"
    for _ in range(200):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 400)))
        markup = (
            "<html><body><article>"
            f'<img src="/images/a.jpg" width="800" height="600" '
            f'alt="{html_lib.escape(raw, quote=True)}" />'
            "</article></body></html>"
        )

        candidates = image_extractor.extract_candidates(markup, "https://example.com/a")
        alt = candidates[0].alt

        if alt is not None:
            assert alt == " ".join(alt.split())
            assert 5 <= len(alt) <= 300
            assert not is_boilerplate_alt(alt)


def test_long_source_alt_capped(image_extractor):
    html = f"""
    <html><body><article>
        <img src="/images/a.jpg" width="800" height="600" alt="{'descripción ' * 100}" />
    </article></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")

    assert candidates[0].alt is not None
    assert len(candidates[0].alt) <= 300


def test_metadata_site_logo_is_skipped(image_extractor):
    html = """
    <html><head>
        <meta property="og:image" content="https://www.biorxiv.org/sites/default/files/images/biorxiv_logo_homepage7-5-small.png" />
        <meta name="twitter:image" content="https://example.com/analogous-study.jpg" />
    </head><body></body></html>
    """
    candidates = image_extractor.extract_candidates(html, "https://example.com/a")
    urls = [c.url for c in candidates]
    assert all("biorxiv_logo" not in u for u in urls)
    assert "https://example.com/analogous-study.jpg" in urls
