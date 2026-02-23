"""Load replay helpers for profiling collectors under synthetic workloads."""

from __future__ import annotations

import contextlib
import json
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterator, List, MutableMapping, Optional, Sequence
from xml.sax.saxutils import escape


@dataclass(frozen=True)
class ReplayArticle:
    """Article specification captured in a replay event."""

    link: str
    title: str
    summary: str
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    published: str | None = None
    doi: str | None = None

    @classmethod
    def from_mapping(cls, payload: MutableMapping[str, Any]) -> "ReplayArticle":
        return cls(
            link=str(payload.get("link")),
            title=str(payload.get("title", "")),
            summary=str(payload.get("summary", "")),
            authors=tuple(str(item) for item in payload.get("authors", [])),
            tags=tuple(str(item) for item in payload.get("tags", [])),
            published=payload.get("published"),
            doi=payload.get("doi"),
        )


@dataclass(frozen=True)
class ReplayEvent:
    """Snapshot describing one feed fetch during load replay."""

    source_id: str
    url: str
    feed_title: str
    category: str
    credibility_score: float
    latency_ms: float
    status_code: int
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    articles: tuple[ReplayArticle, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, payload: MutableMapping[str, Any]) -> "ReplayEvent":
        articles_payload = payload.get("articles", [])
        articles = tuple(
            ReplayArticle.from_mapping(dict(item)) for item in articles_payload
        )
        return cls(
            source_id=str(payload["source_id"]),
            url=str(payload["url"]),
            feed_title=str(payload.get("feed_title", payload["source_id"])),
            category=str(payload.get("category", "general")),
            credibility_score=float(payload.get("credibility_score", 0.5)),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            status_code=int(payload.get("status_code", 200)),
            etag=payload.get("etag"),
            last_modified=payload.get("last_modified"),
            content_hash=payload.get("content_hash"),
            articles=articles,
        )


class MemoryFeedStore:
    """In-memory stand-in for the database manager used in tests and profiling."""

    def __init__(self) -> None:
        self.saved_articles: list[dict[str, Any]] = []
        self.metadata: dict[str, dict[str, Optional[str]]] = {}
        self.stats_updates: dict[str, dict[str, Any]] = {}

    # DatabaseManager compatibility -------------------------------------------------
    def get_source_feed_metadata(self, source_id: str) -> Dict[str, Optional[str]]:
        return self.metadata.get(
            source_id,
            {"etag": None, "last_modified": None, "content_hash": None},
        )

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        current = self.metadata.get(
            source_id,
            {"etag": None, "last_modified": None, "content_hash": None},
        )
        if etag is not None:
            current["etag"] = etag
        if last_modified is not None:
            current["last_modified"] = last_modified
        if content_hash is not None:
            current["content_hash"] = content_hash
        self.metadata[source_id] = current

    def update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        self.stats_updates[source_id] = dict(stats)

    def save_article(self, article: dict[str, Any]) -> dict[str, Any]:
        self.saved_articles.append(article)
        return article


class ReplayFeedSource:
    """
    Stable replay seam consumed by RSSCollector via set_feed_replay_source().
    It returns synthetic feed bytes for deterministic, network-free runs.
    """

    def __init__(self, session: "CollectorReplaySession"):
        self._session = session

    def fetch_feed(
        self,
        *,
        source_id: str,
        source_config: Dict[str, Any],  # noqa: ARG002 - reserved for future use
        cached_headers: Dict[str, Optional[str]],  # noqa: ARG002
        request_headers: Dict[str, str],  # noqa: ARG002
        db_manager: Any,
    ) -> Dict[str, Any]:
        event = self._session._pop_event(source_id)
        self._session._log_request(source_id, event)

        if event.latency_ms:
            time.sleep(event.latency_ms / 1000.0)

        with contextlib.suppress(Exception):
            db_manager.update_source_feed_metadata(
                source_id,
                etag=event.etag,
                last_modified=event.last_modified,
                content_hash=event.content_hash,
            )

        if event.status_code == 304:
            return {
                "success": True,
                "status_code": 304,
                "content": None,
                "url": event.url,
            }

        if event.status_code >= 400:
            return {
                "success": False,
                "status_code": event.status_code,
                "content": None,
                "url": event.url,
                "error_message": f"HTTP {event.status_code}",
            }

        content = self._render_feed(event).encode("utf-8")
        return {
            "success": True,
            "status_code": event.status_code,
            "content": content,
            "url": event.url,
            "encoding": "utf-8",
        }

    @staticmethod
    def _render_feed(event: ReplayEvent) -> str:
        items: list[str] = []
        for article in event.articles:
            categories = "".join(
                f"<category>{escape(tag)}</category>" for tag in article.tags
            )
            author = (
                f"<author>{escape(', '.join(article.authors))}</author>"
                if article.authors
                else ""
            )
            published = ""
            if article.published:
                published = f"<pubDate>{ReplayFeedSource._to_rfc2822(article.published)}</pubDate>"
            items.append(
                "<item>"
                f"<title>{escape(article.title)}</title>"
                f"<link>{escape(article.link)}</link>"
                f"<guid>{escape(article.link)}</guid>"
                f"{author}"
                f"<description>{escape(article.summary)}</description>"
                f"{published}"
                f"{categories}"
                "</item>"
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0">'
            "<channel>"
            f"<title>{escape(event.feed_title)}</title>"
            f"<link>{escape(event.url)}</link>"
            f"<description>Replay feed for {escape(event.source_id)}</description>"
            f"{''.join(items)}"
            "</channel>"
            "</rss>"
        )

    @staticmethod
    def _to_rfc2822(value: str) -> str:
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


class CollectorReplaySession:
    """Manage deterministic replay of feed fetches for collectors."""

    def __init__(self, events: Sequence[ReplayEvent]):
        if not events:
            raise ValueError("CollectorReplaySession requires at least one event")
        self._queues: dict[str, Deque[ReplayEvent]] = defaultdict(deque)
        self._sources: dict[str, ReplayEvent] = {}
        for event in events:
            if event.source_id not in self._sources:
                self._sources[event.source_id] = event
            self._queues[event.source_id].append(event)
        self.requests: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ utilities --
    def build_source_config(self) -> Dict[str, Dict[str, Any]]:
        """Construct collector-ready source configuration mapping."""

        config: Dict[str, Dict[str, Any]] = {}
        for source_id, template in self._sources.items():
            config[source_id] = {
                "name": template.feed_title,
                "url": template.url,
                "category": template.category,
                "credibility_score": template.credibility_score,
            }
        return config

    def create_replay_source(self) -> ReplayFeedSource:
        return ReplayFeedSource(self)

    def _pop_event(self, source_id: str) -> ReplayEvent:
        try:
            queue = self._queues[source_id]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"Unknown source_id during replay: {source_id}") from exc
        if not queue:
            raise RuntimeError(
                f"Replay event queue exhausted for source {source_id}; add more samples"
            )
        return queue.popleft()

    def _log_request(self, source_id: str, event: ReplayEvent) -> None:
        self.requests.append(
            {
                "source_id": source_id,
                "latency_ms": event.latency_ms,
                "status_code": event.status_code,
            }
        )

    @contextmanager
    def patch_collector(
        self, collector: Any, *, asynchronous: bool = False  # noqa: ARG002
    ) -> Iterator[None]:
        """
        Attach replay source through the collector's stable public seam.
        No private monkey-patching is performed.
        """
        if not hasattr(collector, "set_feed_replay_source"):
            raise TypeError(
                "Collector does not expose set_feed_replay_source() replay seam."
            )
        collector.set_feed_replay_source(self.create_replay_source())
        try:
            yield
        finally:
            collector.set_feed_replay_source(None)


def load_replay_fixture(path: str | Path) -> List[ReplayEvent]:
    """Load replay events stored as JSON Lines."""

    source = Path(path)
    events: List[ReplayEvent] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            events.append(ReplayEvent.from_mapping(payload))
    return events


__all__ = [
    "CollectorReplaySession",
    "MemoryFeedStore",
    "ReplayEvent",
    "ReplayFeedSource",
    "load_replay_fixture",
]
