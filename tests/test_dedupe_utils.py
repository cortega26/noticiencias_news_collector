from src.utils.dedupe import (
    normalize_article_text,
    sha256_hex,
    simhash64,
    hamming_distance,
    duplication_confidence,
)


def test_normalize_article_text_basic():
    title = "  Breaking  Discovery!  "
    summary = (
        "<p>The post <strong>Breaking Discovery</strong> appeared first on Site</p>"
    )
    norm_title, norm_summary, combined = normalize_article_text(title, summary)
    assert norm_title == "Breaking Discovery!"
    assert "script" not in norm_summary.lower()
    assert "Breaking" in combined


def test_simhash_hamming_distance():
    _, _, text_a = normalize_article_text("AI breakthrough", "Scientists reveal new AI")
    _, _, text_b = normalize_article_text(
        "AI breakthrough", "Scientists reveal new AI tool"
    )
    hash_a = simhash64(text_a)
    hash_b = simhash64(text_b)
    distance = hamming_distance(hash_a, hash_b)
    assert distance >= 0
    assert duplication_confidence(distance) <= 1.0


def test_sha256_hex_deterministic():
    value = "normalized text"
    assert sha256_hex(value) == sha256_hex(value)
