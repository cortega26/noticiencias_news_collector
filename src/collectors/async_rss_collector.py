# src/collectors/async_rss_collector.py
"""Async RSS collector with parity to the synchronous implementation."""

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING
from urllib.parse import urlparse
import urllib.robotparser as robotparser

import httpx
import feedparser

from .rate_limit_utils import calculate_effective_delay
from .rss_collector import RSSCollector

if TYPE_CHECKING:  # pragma: no cover - typing aid
    from src.utils.logger import NewsCollectorLogger
from config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG, ROBOTS_CONFIG


class AsyncRSSCollector(RSSCollector):
    def __init__(
        self, logger_factory: Optional["NewsCollectorLogger"] = None
    ) -> None:
        super().__init__(logger_factory=logger_factory)
        # Estado asíncrono
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        self._domain_next_time: Dict[str, float] = {}

    # Helpers async
    async def _aget_robots(
        self, client: httpx.AsyncClient, domain: str
    ) -> Optional[robotparser.RobotFileParser]:
        if not ROBOTS_CONFIG["respect_robots"]:
            return None
        now = time.time()
        ttl = ROBOTS_CONFIG["cache_ttl_seconds"]
        cached = self._robots_cache.get(domain)
        if cached and (now - cached[0] < ttl):
            return cached[1]
        try:
            url = f"https://{domain}/robots.txt"
            resp = await client.get(url, timeout=5.0)
            if resp.status_code >= 400:
                return None
            rp = robotparser.RobotFileParser()
            rp.parse(resp.text.splitlines())
            self._robots_cache[domain] = (now, rp)
            return rp
        except Exception:
            return None

    async def _arespect_robots(
        self, client: httpx.AsyncClient, url: str
    ) -> Tuple[bool, Optional[float]]:
        if not ROBOTS_CONFIG["respect_robots"]:
            return (True, None)
        domain = urlparse(url).netloc
        rp = await self._aget_robots(client, domain)
        if not rp:
            return (True, None)
        ua = COLLECTION_CONFIG["user_agent"]
        try:
            allowed = rp.can_fetch(ua, url)
        except Exception:
            allowed = True
        try:
            delay = rp.crawl_delay(ua)
        except Exception:
            delay = None
        return (allowed, delay)

    async def _a_enforce_domain_rate_limit(
        self,
        domain: str,
        robots_delay: Optional[float],
        source_min_delay: Optional[float] = None,
    ):
        lock = self._domain_locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = time.time()
            effective_delay = calculate_effective_delay(
                domain, robots_delay, source_min_delay
            )
            jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))
            next_time = self._domain_next_time.get(domain, 0.0)
            wait = (next_time + effective_delay + jitter) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._domain_next_time[domain] = time.time()

    async def _fetch_feed_async(
        self, client: httpx.AsyncClient, source_id: str, feed_url: str
    ) -> Tuple[Optional[str], Optional[int]]:
        """Fetches a feed using conditional headers and async-friendly backoff."""

        max_retries = RATE_LIMITING_CONFIG["max_retries"]
        cached_headers: Dict[str, Optional[str]] = {"etag": None, "last_modified": None}

        try:
            cached_headers = self.db_manager.get_source_feed_metadata(source_id)
        except Exception as metadata_error:
            self._emit_log(
                "warning",
                "collector.feed.metadata_lookup_failed",
                source_id=source_id,
                details={"error": str(metadata_error)},
            )

        for attempt in range(0, max_retries + 1):
            try:
                conditional_headers: Dict[str, str] = {}
                if cached_headers.get("etag"):
                    conditional_headers["If-None-Match"] = cached_headers["etag"]
                if cached_headers.get("last_modified"):
                    conditional_headers["If-Modified-Since"] = cached_headers[
                        "last_modified"
                    ]

                response = await client.get(
                    feed_url,
                    timeout=COLLECTION_CONFIG["request_timeout"],
                    headers=conditional_headers or None,
                )

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < max_retries:
                        base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
                        max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
                        jitter = random.uniform(
                            0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3)
                        )
                        delay = min(max_b, (base * (2**attempt)) + jitter)
                        await asyncio.sleep(delay)
                        continue
                    self._emit_log(
                        "warning",
                        "collector.feed.status_retry_exhausted",
                        source_id=source_id,
                        details={
                            "status_code": response.status_code,
                            "url": feed_url,
                        },
                    )
                    return (None, response.status_code)

                if response.status_code == 304:
                    if response.headers.get("ETag") or response.headers.get(
                        "Last-Modified"
                    ):
                        try:
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                            )
                        except Exception as update_error:
                            self._emit_log(
                                "warning",
                                "collector.feed.metadata_update_failed",
                                source_id=source_id,
                                details={
                                    "error": str(update_error),
                                    "status_code": 304,
                                },
                            )
                    return (None, 304)

                response.raise_for_status()

                content_type = response.headers.get("content-type", "").lower()
                if not any(
                    xml_type in content_type for xml_type in ["xml", "rss", "atom"]
                ):
                    self._emit_log(
                        "warning",
                        "collector.feed.suspicious_content_type",
                        source_id=source_id,
                        details={"content_type": content_type, "url": feed_url},
                    )

                if len(response.content) > 10 * 1024 * 1024:
                    self._emit_log(
                        "warning",
                        "collector.feed.too_large",
                        source_id=source_id,
                        details={"bytes": len(response.content), "url": feed_url},
                    )
                    return (None, response.status_code)

                if response.headers.get("ETag") or response.headers.get(
                    "Last-Modified"
                ):
                    try:
                        self.db_manager.update_source_feed_metadata(
                            source_id,
                            etag=response.headers.get("ETag"),
                            last_modified=response.headers.get("Last-Modified"),
                        )
                    except Exception as update_error:
                        self._emit_log(
                            "warning",
                            "collector.feed.metadata_update_failed",
                            source_id=source_id,
                            details={
                                "error": str(update_error),
                                "status_code": response.status_code,
                            },
                        )

                return (response.text, response.status_code)

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                if attempt < max_retries:
                    base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
                    max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
                    jitter = random.uniform(
                        0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3)
                    )
                    delay = min(max_b, (base * (2**attempt)) + jitter)
                    await asyncio.sleep(delay)
                    continue
                self._emit_log(
                    "warning",
                    "collector.feed.retry_exhausted",
                    source_id=source_id,
                    details={"error": str(exc), "url": feed_url},
                )
                return (None, None)
            except httpx.HTTPStatusError as exc:  # pragma: no cover - defensive
                self._emit_log(
                    "error",
                    "collector.feed.fetch_exception",
                    source_id=source_id,
                    details={"error": str(exc), "url": feed_url},
                )
                return (None, None)
            except Exception as exc:  # pragma: no cover - defensive
                self._emit_log(
                    "error",
                    "collector.feed.fetch_exception",
                    source_id=source_id,
                    details={"error": str(exc), "url": feed_url},
                )
                return (None, None)

        return (None, None)

    async def _process_source_async(
        self, client: httpx.AsyncClient, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        stats = {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": None,
            "processing_time": 0,
        }
        start = time.time()
        try:
            # Idempotent job key
            job_key = self._make_job_key(source_id, source_config["url"])
            if self._is_duplicate_job(job_key):
                stats["success"] = True
                return stats
            self._register_job(job_key)

            allowed, robots_delay = await self._arespect_robots(
                client, source_config["url"]
            )
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                self._send_to_dlq(source_id, source_config["url"], "robots_disallowed")
                return stats
            domain = urlparse(source_config["url"]).netloc
            await self._a_enforce_domain_rate_limit(
                domain, robots_delay, source_config.get("min_delay_seconds")
            )

            feed_content, status_code = await self._fetch_feed_async(
                client, source_id, source_config["url"]
            )
            if status_code == 304:
                stats["success"] = True
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            parsed_feed = feedparser.parse(feed_content)
            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = (
                    f"Feed malformado: {parsed_feed.bozo_exception}"
                )
                return stats

            try:
                raw_articles = self._extract_articles_from_feed(
                    parsed_feed, source_config, source_id
                )
            except TypeError:
                raw_articles = self._extract_articles_from_feed(  # type: ignore[misc]
                    parsed_feed, source_config
                )
            stats["articles_found"] = len(raw_articles)
            if not raw_articles:
                stats["success"] = True
                return stats

            saved = 0
            for raw_article in raw_articles:
                try:
                    processed_article = self._process_article(
                        raw_article, source_id, source_config
                    )
                    if processed_article and self._save_article(processed_article):
                        saved += 1
                except Exception as exc:
                    self._emit_log(
                        "error",
                        "collector.article.process_error",
                        source_id=source_id,
                        details={"error": str(exc), "url": raw_article.get("url")},
                    )
                    self.session_stats["errors_encountered"] += 1
            stats["articles_saved"] = saved
            stats["success"] = True
            return stats
        except Exception as exc:
            stats["error_message"] = f"Error inesperado: {exc}"
            self._emit_log(
                "error",
                "collector.source.exception",
                source_id=source_id,
                details={"error": str(exc)},
            )
            return stats
        finally:
            stats["processing_time"] = time.time() - start
            self._update_source_stats(source_id, stats)
            self.session_stats["sources_checked"] += 1
            self.session_stats["articles_found"] += stats["articles_found"]
            self.session_stats["articles_saved"] += stats["articles_saved"]

    async def collect_from_multiple_sources_async(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        self.start_time = datetime.now(timezone.utc)
        self._reset_stats()

        self._emit_log(
            "info",
            "collector.batch.start",
            latency=0.0,
            details={"sources": len(sources_config)},
        )

        headers = {
            "User-Agent": COLLECTION_CONFIG["user_agent"],
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }

        source_results: Dict[str, Dict[str, Any]] = {}
        sem = asyncio.Semaphore(COLLECTION_CONFIG["max_concurrent_requests"])

        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:

            async def run_one(sid: str, cfg: Dict[str, Any]):
                try:
                    async with sem:
                        result = await self._process_source_async(client, sid, cfg)
                except Exception as exc:  # pragma: no cover - defensive
                    self._emit_log(
                        "error",
                        "collector.source.exception",
                        source_id=sid,
                        details={"error": str(exc)},
                    )
                    result = {
                        "source_id": sid,
                        "success": False,
                        "articles_found": 0,
                        "articles_saved": 0,
                        "error_message": f"Error inesperado: {exc}",
                        "processing_time": 0,
                    }
                source_results[sid] = result

            for source_id, source_config in sources_config.items():
                try:
                    self._pre_process_source(source_id, source_config)
                except Exception as exc:  # pragma: no cover - defensive
                    self._emit_log(
                        "warning",
                        "collector.source.preprocess_failed",
                        source_id=source_id,
                        details={"error": str(exc)},
                    )

            tasks = [run_one(sid, cfg) for sid, cfg in sources_config.items()]
            await asyncio.gather(*tasks)

        for source_id, source_config in sources_config.items():
            result = source_results.get(
                source_id,
                {
                    "source_id": source_id,
                    "success": False,
                    "articles_found": 0,
                    "articles_saved": 0,
                    "error_message": "Sin resultados",
                    "processing_time": 0,
                },
            )
            self._update_global_stats(result)
            try:
                self._post_process_source(source_id, source_config, result)
            except Exception as exc:  # pragma: no cover - defensive
                self._emit_log(
                    "warning",
                    "collector.source.postprocess_failed",
                    source_id=source_id,
                    details={"error": str(exc)},
                )

        end_time = datetime.now(timezone.utc)
        self.stats["processing_time_seconds"] = (
            end_time - self.start_time
        ).total_seconds()

        try:
            self._post_process_collection(source_results)
        except Exception as exc:  # pragma: no cover - defensive
            self._emit_log(
                "warning",
                "collector.batch.postprocess_failed",
                details={"error": str(exc)},
            )

        final_report = self._generate_collection_report(source_results)

        self._emit_log(
            "info",
            "collector.batch.completed",
            latency=self.stats["processing_time_seconds"],
            details={
                "articles_saved": self.stats["total_articles_saved"],
                "articles_found": self.stats["total_articles_found"],
                "sources_processed": self.stats["total_sources_processed"],
                "errors": self.stats["total_errors"],
            },
        )

        self._reset_runtime_context()
        return final_report
