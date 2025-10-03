#!/usr/bin/env python
"""Benchmark canonicalize_url on 10k synthetic samples."""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.url_canonicalizer import canonicalize_url

BASE_URLS = [
    "https://www.example.com/article/123",
    "http://m.example.net/news/tech/amp/",
    "https://blog.example.org/path/to/post",
    "https://sub.domain.com/resource",
    "https://example.com/",
]

TRACKING_SNIPPETS = [
    "utm_source=newsletter",
    "utm_medium=email",
    "utm_campaign=spring",
    "fbclid=XYZ",
    "gclid=ABC",
    "ref=homepage",
    "amp=1",
    "",
]


def generate_samples(n: int = 10_000) -> List[str]:
    random.seed(1337)
    samples: List[str] = []
    for _ in range(n):
        base = random.choice(BASE_URLS)
        params = [random.choice(TRACKING_SNIPPETS) for _ in range(random.randint(0, 4))]
        params = [p for p in params if p]
        query = "&".join(params)
        url = base
        if params:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{query}"
        # randomly switch scheme/host casing
        if random.random() < 0.5:
            url = url.replace("https://", "HTTPS://").replace("http://", "HTTP://")
        samples.append(url)
    return samples


def main():
    samples = generate_samples()
    start = time.perf_counter()
    for url in samples:
        canonicalize_url(url)
    duration = time.perf_counter() - start
    avg_us = (duration / len(samples)) * 1_000_000
    print(f"Processed {len(samples)} URLs in {duration:.4f}s (avg {avg_us:.2f} µs/url)")


if __name__ == "__main__":
    main()
