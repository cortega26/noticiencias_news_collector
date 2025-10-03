from hypothesis import given, settings
from hypothesis import strategies as st

from src.utils.text_cleaner import clean_html, normalize_text, detect_language_simple


def test_clean_html_removes_boilerplate_and_scripts():
    html = """
    <html><head><style>.x{}</style><script>alert(1)</script></head>
    <body>
      <div>Breaking discovery in physics &amp; AI!</div>
      <p>Continue Reading</p>
    </body></html>
    """
    cleaned = clean_html(html)
    assert "alert(1)" not in cleaned
    assert "Continue Reading".lower() not in cleaned.lower()
    assert "Breaking discovery in physics & AI!" in cleaned


def test_normalize_text_is_deterministic_and_idempotent():
    s = "  The  post   Café  appeared\n first  on  X  "
    a = normalize_text(s)
    b = normalize_text(a)
    assert a == b
    assert "Café" in a


def test_language_detection_simple():
    es = "La ciencia y la tecnología avanzan rápido en el mundo."
    en = "Science and technology advance quickly in the world."
    assert detect_language_simple(es) == "es"
    assert detect_language_simple(en) == "en"


@given(text=st.text())
@settings(max_examples=75)
def test_normalize_text_idempotent_property(text: str) -> None:
    once = normalize_text(text)
    twice = normalize_text(once)
    assert once == twice


@given(
    leading=st.text(),
    body_words=st.lists(st.text(min_size=1), min_size=1, max_size=5),
    trailing=st.text(),
)
@settings(max_examples=50)
def test_clean_html_strips_scripts_and_controls(
    leading: str, body_words: list[str], trailing: str
) -> None:
    payload = f"""
    <html><head><script>malicious()</script><style>body{{}}</style></head>
    <body>{leading}<p>{' '.join(body_words)}</p>{trailing}</body></html>
    """

    cleaned = clean_html(payload)

    assert "malicious()" not in cleaned
    assert "<script" not in cleaned.lower()
    assert "\n" not in cleaned
    assert cleaned == normalize_text(cleaned)
