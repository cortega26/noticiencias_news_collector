"""Deduplication utilities combining exact and near-duplicate detection."""

from __future__ import annotations

import hashlib
import uuid
from typing import Tuple

_BLAKE_PERSONALIZATION = b"noti-simhash"

from src.utils.text_cleaner import clean_html, normalize_text


SIMHASH_BITS = 64
SIMHASH_THRESHOLD_DEFAULT = 10  # Hamming distance threshold


def normalize_article_text(title: str, summary: str) -> Tuple[str, str, str]:
    """Return normalized title, summary (HTML cleaned) and combined text."""
    normalized_title = normalize_text(title or "")
    normalized_summary = normalize_text(clean_html(summary or ""))
    combined = f"{normalized_title} {normalized_summary}".strip()
    return normalized_title, normalized_summary, combined


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def simhash64(text: str, num_bits: int = SIMHASH_BITS) -> int:
    if not text:
        return 0
    tokens = text.split()
    if not tokens:
        return 0
    vector = [0] * num_bits
    digest_size = max(1, (num_bits + 7) // 8)
    for token in tokens:
        digest = hashlib.blake2b(
            token.encode("utf-8"),
            digest_size=digest_size,
            person=_BLAKE_PERSONALIZATION,
        )
        h = int.from_bytes(digest.digest(), "big")
        for i in range(num_bits):
            bit = (h >> i) & 1
            vector[i] += 1 if bit else -1
    result = 0
    for i in range(num_bits):
        if vector[i] >= 0:
            result |= 1 << i
    return result


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def duplication_confidence(distance: int, num_bits: int = SIMHASH_BITS) -> float:
    return max(0.0, 1.0 - (distance / num_bits))


def generate_cluster_id() -> str:
    return str(uuid.uuid4())
