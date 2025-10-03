#!/usr/bin/env python
"""Show duplicate count before/after URL canonicalization."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.url_canonicalizer import canonicalize_url

SAMPLE_URLS = [
    "https://www.example.com/article/123?utm_source=twitter",
    "https://example.com/article/123/",
    "http://m.example.com/article/123?fbclid=foo",
    "https://example.com/article/123/?amp",
    "https://news.site.com/path/story?id=55",
    "https://news.site.com/path/story?id=55&ref=homepage",
    "https://mobile.news.site.com/path/story?id=55",
    "https://blog.example.org/post?gclid=abc",
    "https://blog.example.org/post",
    "https://blog.example.org/post?utm_campaign=spring",
]


def main():
    before = len(set(SAMPLE_URLS))
    canon_urls = [canonicalize_url(url) for url in SAMPLE_URLS]
    after = len(set(canon_urls))

    print("Sample size:", len(SAMPLE_URLS))
    print("Unique URLs before:", before)
    print("Unique URLs after :", after)
    print("Duplicates removed:", before - after)

    counts = Counter(canon_urls)
    print("\nCanonical frequencies:")
    for url, count in counts.items():
        marker = "*" if count > 1 else " "
        print(f"{marker} {count} × {url}")


if __name__ == "__main__":
    main()
