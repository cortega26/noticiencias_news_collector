from news_collector.utils.dedupe import (
    duplication_confidence,
    hamming_distance,
    normalize_article_text,
    sha256_hex,
    simhash64,
)


def test_normalize_article_text():
    # Test cleaning and concatenation
    title = "  My Title  "
    summary = "<p>Summary</p>"
    norm_t, norm_s, combined = normalize_article_text(title, summary)

    assert norm_t == "My Title"
    assert norm_s == "Summary"
    assert combined == "My Title Summary"


def test_sha256_hex():
    text = "hello"
    # echo -n "hello" | sha256sum
    # 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert sha256_hex(text) == expected


def test_simhash_consistency():
    # Deterministic output
    text = "apple banana cherry"
    h1 = simhash64(text)
    h2 = simhash64(text)
    assert h1 == h2
    assert isinstance(h1, int)


def test_hamming_distance():
    # 0 vs 1 (binary 1) -> 1 bit diff
    assert hamming_distance(0, 1) == 1
    # 3 (11) vs 1 (01) -> 1 bit diff
    assert hamming_distance(3, 1) == 1
    # 0 vs 0
    assert hamming_distance(123, 123) == 0


def test_duplication_confidence():
    # 0 distance = 1.0 confidence
    assert duplication_confidence(0) == 1.0
    # 32 distance / 64 bits = 0.5 confidence
    assert duplication_confidence(32, num_bits=64) == 0.5
