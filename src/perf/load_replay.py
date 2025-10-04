"""Load replay helpers for profiling collectors under synthetic workloads."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from types import MethodType
from typing import Any, Deque, Dict, Iterator, List, MutableMapping, Optional, Sequence

import feedparser


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


class ReplayParsedFeed:
    """Lightweight feedparser replacement used during replay."""

    __slots__ = ("bozo", "bozo_exception", "feed", "entries", "_event")

    def __init__(self, event: ReplayEvent):
        self.bozo = 0
        self.bozo_exception = None
        self.feed = type("FeedInfo", (), {"title": event.feed_title})()
        # We do not rely on feedparser entries because we patch extractor.
        self.entries: list[Any] = []
        self._event = event


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
        self._token_map: dict[str, ReplayEvent] = {}
        self._token_counter = count()
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

    def _register_token(self, event: ReplayEvent) -> str:
        token = f"replay://{event.source_id}/{next(self._token_counter)}"
        self._token_map[token] = event
        return token

    def _pop_token(self, token: str) -> ReplayEvent:
        event = self._token_map.pop(token, None)
        if event is None:
            raise RuntimeError(f"No replay event registered for token {token}")
        return event

    @contextmanager
    def _patch_feedparser(self) -> Iterator[None]:
        original_parse = feedparser.parse

        def fake_parse(content: Any, *args: Any, **kwargs: Any):
            if isinstance(content, str) and content.startswith("replay://"):
                event = self._pop_token(content)
                return ReplayParsedFeed(event)
            return original_parse(content, *args, **kwargs)

        feedparser.parse = fake_parse  # type: ignore[assignment]
        try:
            yield
        finally:
            feedparser.parse = original_parse  # type: ignore[assignment]

    def _patch_rate_limits(self, collector: Any, stack: ExitStack) -> None:
        if hasattr(collector, "_enforce_domain_rate_limit"):
            stack.enter_context(
                _patch_method(collector, "_enforce_domain_rate_limit", _noop_rate_limit)
            )
        if hasattr(collector, "_a_enforce_domain_rate_limit"):
            stack.enter_context(
                _patch_method(
                    collector,
                    "_a_enforce_domain_rate_limit",
                    _noop_async_rate_limit,
                )
            )
        if hasattr(collector, "_respect_robots"):
            stack.enter_context(
                _patch_method(collector, "_respect_robots", _allow_all_robots)
            )
        if hasattr(collector, "_arespect_robots"):
            stack.enter_context(
                _patch_method(collector, "_arespect_robots", _allow_all_robots_async)
            )

    def _patch_extractor(self, collector: Any, stack: ExitStack) -> None:
        original_extract = collector._extract_articles_from_feed

        def fake_extract(self: Any, parsed_feed: Any, source_config: Dict[str, Any]):
            if hasattr(parsed_feed, "_event"):
                event: ReplayEvent = parsed_feed._event
                articles: List[Dict[str, Any]] = []
                for article in event.articles:
                    payload = {
                        "url": article.link,
                        "title": article.title,
                        "summary": article.summary,
                        "authors": list(article.authors),
                        "source_metadata": {
                            "feed_title": event.feed_title,
                            "tags": list(article.tags),
                        },
                        "original_url": article.link,
                    }
                    if article.doi:
                        payload["source_metadata"]["doi"] = article.doi
                    articles.append(payload)
                return articles
            return original_extract(parsed_feed, source_config)

        stack.enter_context(
            _patch_method(collector, "_extract_articles_from_feed", fake_extract)
        )

    def _patch_process(self, collector: Any, stack: ExitStack) -> None:
        def fake_process(
            self: Any,
            raw_article: Dict[str, Any],
            source_id: str,
            source_config: Dict[str, Any],
        ) -> Dict[str, Any]:
            document = {
                "url": raw_article["url"],
                "title": raw_article["title"],
                "summary": raw_article.get("summary", ""),
                "source_id": source_id,
                "source_name": source_config["name"],
                "category": source_config["category"],
                "language": "en",
                "published_date": raw_article.get("published_date"),
                "published_tz_offset_minutes": raw_article.get(
                    "published_tz_offset_minutes"
                ),
                "published_tz_name": raw_article.get("published_tz_name"),
                "authors": raw_article.get("authors", []),
                "article_metadata": {
                    "source_metadata": raw_article.get("source_metadata", {}),
                    "credibility_score": source_config["credibility_score"],
                    "processing_timestamp": datetime.now(timezone.utc).isoformat(),
                    "original_url": raw_article.get("original_url", raw_article["url"]),
                    "replay": True,
                },
            }
            return document

        stack.enter_context(_patch_method(collector, "_process_article", fake_process))

    def _patch_fetch(
        self, collector: Any, stack: ExitStack, *, asynchronous: bool
    ) -> None:
        if asynchronous:

            async def fake_fetch_async(
                self: Any, client: Any, source_id: str, feed_url: str
            ) -> tuple[Optional[str], Optional[int]]:
                event = self._replay_session._pop_event(source_id)
                self._replay_session._log_request(source_id, event)
                if event.status_code == 304:
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=event.etag,
                        last_modified=event.last_modified,
                        content_hash=event.content_hash,
                    )
                    await asyncio.sleep(event.latency_ms / 1000.0)
                    return (None, 304)
                token = self._replay_session._register_token(event)
                await asyncio.sleep(event.latency_ms / 1000.0)
                self.db_manager.update_source_feed_metadata(
                    source_id,
                    etag=event.etag,
                    last_modified=event.last_modified,
                    content_hash=event.content_hash,
                )
                return (token, event.status_code)

            stack.enter_context(
                _patch_method(collector, "_fetch_feed_async", fake_fetch_async)
            )
        else:

            def fake_fetch(
                self: Any, source_id: str, feed_url: str
            ) -> tuple[Optional[str], Optional[int]]:
                event = self._replay_session._pop_event(source_id)
                self._replay_session._log_request(source_id, event)
                if event.latency_ms:
                    time.sleep(event.latency_ms / 1000.0)
                if event.status_code == 304:
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=event.etag,
                        last_modified=event.last_modified,
                        content_hash=event.content_hash,
                    )
                    return (None, 304)
                token = self._replay_session._register_token(event)
                self.db_manager.update_source_feed_metadata(
                    source_id,
                    etag=event.etag,
                    last_modified=event.last_modified,
                    content_hash=event.content_hash,
                )
                return (token, event.status_code)

            stack.enter_context(_patch_method(collector, "_fetch_feed", fake_fetch))

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
        self, collector: Any, *, asynchronous: bool = False
    ) -> Iterator[None]:
        """Patch a collector instance so it replays events instead of hitting the network."""

        collector._replay_session = self  # type: ignore[attr-defined]
        stack = ExitStack()
        try:
            stack.enter_context(self._patch_feedparser())
            self._patch_rate_limits(collector, stack)
            self._patch_extractor(collector, stack)
            self._patch_process(collector, stack)
            self._patch_fetch(collector, stack, asynchronous=asynchronous)
            yield
        finally:
            stack.close()
            delattr(collector, "_replay_session")


def load_replay_fixture(path: str | Path) -> List[ReplayEvent]:
    """Load replay events stored as JSON Lines."""

    source = Path(path)
    events: List[ReplayEvent] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            events.append(ReplayEvent.from_mapping(payload))
    return events


# --------------------------------------------------------------------------- helpers


def _patch_method(obj: Any, name: str, func: Any) -> contextmanager[None]:
    @contextmanager
    def _inner() -> Iterator[None]:
        original = getattr(obj, name)
        setattr(obj, name, MethodType(func, obj))
        try:
            yield
        finally:
            setattr(obj, name, original)

    return _inner()


def _noop_rate_limit(self: Any, *args: Any, **kwargs: Any) -> None:
    return None


async def _noop_async_rate_limit(self: Any, *args: Any, **kwargs: Any) -> None:
    return None


def _allow_all_robots(self: Any, url: str) -> tuple[bool, Optional[float]]:
    return (True, None)


async def _allow_all_robots_async(
    self: Any, client: Any, url: str
) -> tuple[bool, Optional[float]]:
    return (True, None)


__all__ = [
    "CollectorReplaySession",
    "MemoryFeedStore",
    "ReplayEvent",
    "load_replay_fixture",
]
