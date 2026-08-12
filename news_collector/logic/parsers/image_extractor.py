import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


@dataclass
class ImageCandidate:
    url: str
    source: str  # 'feed', 'og:image', 'twitter:image', 'dom'
    score: float = 0.0
    width: Optional[int] = None
    height: Optional[int] = None


class ImageExtractor:
    """
    Robust image extractor for news articles.
    Implements a multi-layer strategy: Metadata -> DOM -> Heuristics.
    """

    # known tracking pixels or icons to ignore
    BLACKLIST_PATTERNS = [
        r"logo",
        r"icon",
        r"avatar",
        r"width=\d{1,2}&",  # very small explicitly
        r"tracker",
        r"pixel",
        r"ads",
        r"banner",
        r"social",
        r"share",
        r"button",
        r"spacer",
        r"placeholder",
    ]

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def extract_candidates(self, html: str, base_url: str) -> List[ImageCandidate]:
        """
        Extracts valid image candidates from HTML content.
        Returns a sorted list of candidates (best first).
        """
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        candidates: List[ImageCandidate] = []
        seen_urls: Set[str] = set()

        # 1. Metadata Extraction (High Confidence)
        self._extract_metadata(soup, base_url, candidates, seen_urls)

        # 2. DOM Heuristics
        self._extract_from_dom(soup, base_url, candidates, seen_urls)

        # 3. Score and Sort
        self._score_candidates(candidates)
        candidates.sort(key=lambda x: x.score, reverse=True)

        return candidates

    def _extract_metadata(
        self,
        soup: BeautifulSoup,
        base_url: str,
        candidates: List[ImageCandidate],
        seen: Set[str],
    ):
        """Extracts images from OpenGraph and Twitter meta tags."""
        meta_tags: List[Dict[str, Any]] = [
            {"property": "og:image"},
            {"property": "og:image:secure_url"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"},
            {"itemprop": "image"},
        ]

        for tag_query in meta_tags:
            tag = soup.find("meta", attrs=tag_query)
            if tag:
                content = tag.get("content")
                if content:
                    url = self._normalize_url(str(content), base_url)
                    if url and url not in seen:
                        candidates.append(
                            ImageCandidate(
                                url=url,
                                source=f"meta:{list(tag_query.values())[0]}",
                                score=10.0,
                            )
                        )
                        seen.add(url)

    def _extract_from_dom(  # noqa: C901
        self,
        soup: BeautifulSoup,
        base_url: str,
        candidates: List[ImageCandidate],
        seen: Set[str],
    ):
        """Extracts images from the main article body."""
        # Focus on the article content to avoid sidebars/footers
        article_body = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile(r"content|article|entry|post"))
            or soup
        )

        images = article_body.find_all("img")
        for img in images:
            # Handle lazy loading
            src = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("src")
            )

            if src:
                url = self._normalize_url(str(src), base_url)
                if url and url not in seen:
                    # Filter out likely icons/logos based on filename
                    if self._is_blacklisted(url):
                        continue

                    # basic heuristic scoring based on attributes
                    score = 1.0
                    w_attr = img.get("width")
                    h_attr = img.get("height")
                    width = self._parse_dimension(
                        str(w_attr) if w_attr is not None else None
                    )
                    height = self._parse_dimension(
                        str(h_attr) if h_attr is not None else None
                    )

                    if width and width < 150:
                        continue  # too small
                    if height and height < 150:
                        continue

                    if width and width > 600:
                        score += 2.0

                    # Penalize if likely logo based on class/id
                    c_attr = img.get("class")
                    if isinstance(c_attr, list):
                        classes = " ".join(str(c) for c in c_attr)
                    else:
                        classes = str(c_attr) if c_attr else ""
                    i_attr = img.get("id")
                    if isinstance(i_attr, list):
                        ids = " ".join(str(i) for i in i_attr)
                    else:
                        ids = str(i_attr) if i_attr else ""
                    if "logo" in classes.lower() or "logo" in ids.lower():
                        continue

                    candidates.append(
                        ImageCandidate(
                            url=url,
                            source="dom",
                            score=score,
                            width=width,
                            height=height,
                        )
                    )
                    seen.add(url)

    def validate_image(self, candidate: ImageCandidate) -> bool:
        """
        Validates an image candidate by checking headers (and potentially size).
        """
        try:
            # First try HEAD
            resp = self.session.head(candidate.url, timeout=5, allow_redirects=True)
            if resp.status_code == 405:  # Method Not Allowed
                resp = self.session.get(candidate.url, stream=True, timeout=5)
                resp.close()

            if resp.status_code != 200:
                logger.debug(
                    f"Image validation failed for {candidate.url}: Status {resp.status_code}"
                )
                return False

            content_type = resp.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                logger.debug(
                    f"Image validation failed for {candidate.url}: Invalid Content-Type {content_type}"
                )
                return False

            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) < 5000:  # 5KB min
                logger.debug(
                    f"Image validation failed for {candidate.url}: Too small ({content_length} bytes)"
                )
                return False

            return True

        except Exception as e:
            logger.debug(f"Image validation error for {candidate.url}: {e}")
            return False

    def _normalize_url(self, url: str, base_url: str) -> Optional[str]:
        try:
            full_url = urljoin(base_url, url.strip())
            parsed = urlparse(full_url)
            if not parsed.scheme or not parsed.netloc:
                return None
            if parsed.scheme not in ("http", "https"):
                return None
            return full_url
        except Exception:
            return None

    def _is_blacklisted(self, url: str) -> bool:
        url_lower = url.lower()
        return any(re.search(pattern, url_lower) for pattern in self.BLACKLIST_PATTERNS)

    def _parse_dimension(self, value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            # handle "100px" or just "100"
            return int(float(re.sub(r"[^\d.]", "", value)))
        except ValueError:
            return None

    def _score_candidates(self, candidates: List[ImageCandidate]):
        # normalize scores if needed
        pass
