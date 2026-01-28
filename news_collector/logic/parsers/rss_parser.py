import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import feedparser
from news_collector.utils.datetime_utils import parse_to_utc_with_tzinfo
from news_collector.utils.text_cleaner import clean_html
from news_collector.utils.url_canonicalizer import canonicalize_url


class RssParser:
    """
    Pure logic parser for RSS/Atom feeds.
    Decoupled from network I/O and database storage.
    """

    def parse_feed_content(self, content: Union[str, bytes]) -> Any:
        """Parses raw content into a feed object."""
        return feedparser.parse(content)

    def is_acceptable_bozo(self, parsed_feed) -> bool:
        """Determines if a malformed feed is acceptable."""
        if not parsed_feed.bozo:
            return True
        acceptable_exceptions = ["InvalidDocument", "UndeclaredNamespace"]
        exception_name = parsed_feed.bozo_exception.__class__.__name__
        return exception_name in acceptable_exceptions

    def extract_items(
        self, parsed_feed, source_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extracts and normalizes items from a parsed feed.
        """
        candidates = []
        feed_info = getattr(parsed_feed, "feed", None)

        # We don't limit here (the collector limits *fetched* items, but parser should just parse what it's given)
        # However, to match legacy behavior, we can handle slicing in the collector.
        # But wait, looking at legacy code: for entry in parsed_feed.entries[:fetch_limit]

        for entry in parsed_feed.entries:
            try:
                original_url = entry.get("link", "")
                if not original_url:
                    continue

                pub_dt, pub_off_min, pub_tz_name = self._parse_timestamp(entry)

                candidate = {
                    "title": self._clean_title(entry.get("title", "Sin título")),
                    "url": canonicalize_url(original_url),
                    "original_url": original_url,
                    "summary": self._extract_summary(entry),
                    "published_date": pub_dt,
                    "published_tz_offset_minutes": pub_off_min,
                    "published_tz_name": pub_tz_name,
                    "authors": self._extract_authors(entry),
                    "category": source_config.get("category", "general"),
                    "image_url": self._extract_image_url(entry),
                    "source_metadata": self._extract_source_metadata(entry, feed_info),
                    "entry_ref": entry,  # Kept for backward compat if needed, but risky for serialization
                }

                # Basic validation
                if len(candidate["title"]) < 5:
                    continue

                candidates.append(candidate)
            except Exception:  # noqa: S112
                continue

        return candidates

    def _parse_timestamp(self, entry) -> Tuple[datetime, int, str]:
        date_fields = ["published_parsed", "updated_parsed", "published", "updated"]
        for field in date_fields:
            if hasattr(entry, field):
                val = getattr(entry, field)
                if val:
                    try:
                        return parse_to_utc_with_tzinfo(val)
                    except Exception:  # noqa: S112
                        continue
        return parse_to_utc_with_tzinfo(None)

    def _clean_title(self, title: str) -> str:
        # Simple cleanup

        # Remove multiple spaces
        return " ".join(title.split())

    def _extract_summary(self, entry) -> str:
        content_fields = ["summary", "description", "content"]
        for field in content_fields:
            if hasattr(entry, field):
                content = getattr(entry, field)
                # Handle list/dict variants in feedparser
                if isinstance(content, list) and content:
                    content = (
                        content[0].get("value", "")
                        if isinstance(content[0], dict)
                        else str(content[0])
                    )
                elif isinstance(content, dict):
                    content = content.get("value", "")

                if content and isinstance(content, str):
                    cleaned = clean_html(content)
                    if len(cleaned) >= 10:  # Lowered from 50 to allow short summaries (validation happens in Collector)
                        return cleaned
        return ""

    def _extract_authors(self, entry) -> List[str]:
        authors = []
        if hasattr(entry, "author") and entry.author:
            authors.append(self._clean_title(entry.author))  # clean_text logic

        if hasattr(entry, "authors") and entry.authors:
            for author in entry.authors:
                if isinstance(author, dict):
                    name = author.get("name") or author.get("email", "")
                else:
                    name = str(author)
                if name:
                    authors.append(self._clean_title(name))

        # Custom tags
        if hasattr(entry, "tags"):
            for tag in entry.tags:
                if "author" in tag.get("term", "").lower():
                    authors.append(self._clean_title(tag.get("term", "")))

        return list(set(authors))

    def _extract_image_url(self, entry) -> Optional[str]:  # noqa: C901
        # 1. Media Content
        if hasattr(entry, "media_content"):
            for media in entry.media_content:
                if media.get("medium") == "image" and media.get("url"):
                    return str(media["url"])
        # 2. Enclosures
        if hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image/") and enc.get("href"):
                    return str(enc["href"])
        # 3. Media Thumbnail
        if hasattr(entry, "media_thumbnail"):
            thumbs = entry.media_thumbnail
            if isinstance(thumbs, list) and thumbs:
                return str(thumbs[0].get("url"))
            elif isinstance(thumbs, dict):
                return str(thumbs.get("url"))
        # 4. Links
        if hasattr(entry, "links"):
            for link in entry.links:
                if link.get("type", "").startswith("image/") and link.get("href"):
                    return str(link["href"])
        return None

    def _extract_source_metadata(self, entry, feed_info) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        doi = self._extract_doi(entry)
        if doi:
            metadata["doi"] = doi

        if hasattr(entry, "tags") and entry.tags:
            metadata["tags"] = [
                tag.get("term", "") for tag in entry.tags if tag.get("term")
            ]

        if feed_info and hasattr(feed_info, "title"):
            metadata["feed_title"] = feed_info.title

        if hasattr(entry, "id") and entry.id:
            metadata["entry_id"] = entry.id

        return metadata

    def _extract_doi(self, entry) -> Optional[str]:
        doi_pattern = r"10\.\d{4,}/[-._;()/:\w\[\]]+[^.\s]"
        search_fields = []
        if hasattr(entry, "id"):
            search_fields.append(entry.id)
        if hasattr(entry, "summary"):
            search_fields.append(entry.summary)
        if hasattr(entry, "links"):
            for link in entry.links:
                if link.get("href"):
                    search_fields.append(link["href"])

        for field in search_fields:
            if field and isinstance(field, str):
                match = re.search(doi_pattern, field, re.IGNORECASE)
                if match:
                    return match.group()
        return None
