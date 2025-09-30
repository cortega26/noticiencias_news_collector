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
