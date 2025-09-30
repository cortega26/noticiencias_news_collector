# src/collectors/async_rss_collector.py
"""
Colector RSS asíncrono usando httpx y asyncio.
Mantiene compatibilidad con RSSCollector pero permite concurrencia controlada
entre múltiples dominios/fuentes.
"""

import asyncio
import time
import random
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import urllib.robotparser as robotparser

import httpx
import feedparser

from .rss_collector import RSSCollector, logger
from config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG, ROBOTS_CONFIG


class AsyncRSSCollector(RSSCollector):
    def __init__(self):
        super().__init__()
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
        self, domain: str, robots_delay: Optional[float]
    ):
        lock = self._domain_locks.setdefault(domain, asyncio.Lock())
        async with lock:
            now = time.time()
            base_delay = RATE_LIMITING_CONFIG.get(
                "domain_default_delay", RATE_LIMITING_CONFIG["delay_between_requests"]
            )
            effective_delay = max(
                base_delay,
                robots_delay or 0.0,
                RATE_LIMITING_CONFIG["delay_between_requests"],
            )
            jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))
            next_time = self._domain_next_time.get(domain, 0.0)
            wait = (next_time + effective_delay + jitter) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._domain_next_time[domain] = time.time()

    async def _fetch_feed_async(
        self, client: httpx.AsyncClient, feed_url: str
    ) -> Optional[str]:
        max_retries = RATE_LIMITING_CONFIG["max_retries"]
        for attempt in range(0, max_retries + 1):
            try:
                resp = await client.get(
                    feed_url, timeout=COLLECTION_CONFIG["request_timeout"]
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < max_retries:
                        base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
                        max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
                        jitter = random.uniform(
                            0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3)
                        )
                        delay = min(max_b, (base * (2**attempt)) + jitter)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.warning(
                            f"HTTP {resp.status_code} agotó reintentos para {feed_url}"
                        )
                        return None
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "").lower()
                if not any(x in ct for x in ["xml", "rss", "atom"]):
                    logger.warning(f"⚠️  Content-Type sospechoso: {ct} para {feed_url}")
                if len(resp.content) > 10 * 1024 * 1024:
                    logger.warning(f"⚠️  Feed muy grande (>10MB): {feed_url}")
                    return None
                return resp.text
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as re:
                if attempt < max_retries:
                    base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
                    max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
                    jitter = random.uniform(
                        0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3)
                    )
                    delay = min(max_b, (base * (2**attempt)) + jitter)
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.warning(
                        f"⏰ Timeout/ConnError tras reintentos: {feed_url} | {re}"
                    )
                    return None
        return None

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
            await self._a_enforce_domain_rate_limit(domain, robots_delay)

            feed_content = await self._fetch_feed_async(client, source_config["url"])
            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            parsed_feed = feedparser.parse(feed_content)
            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = (
                    f"Feed malformado: {parsed_feed.bozo_exception}"
                )
                return stats

            raw_articles = self._extract_articles_from_feed(parsed_feed, source_config)
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
                except Exception as e:
                    logger.error(f"Error procesando artículo individual: {e}")
                    self.session_stats["errors_encountered"] += 1
            stats["articles_saved"] = saved
            stats["success"] = True
            return stats
        except Exception as e:
            stats["error_message"] = f"Error inesperado: {str(e)}"
            return stats
        finally:
            stats["processing_time"] = time.time() - start
            self._update_source_stats(source_id, stats)
            self.session_stats["sources_checked"] += 1
            self.session_stats["articles_found"] += stats["articles_found"]
            self.session_stats["articles_saved"] += stats["articles_saved"]

    async def collect_from_multiple_sources_async(
        self, sources_config: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        self.start_time = time.time()
        self._reset_stats()

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
                async with sem:
                    res = await self._process_source_async(client, sid, cfg)
                    source_results[sid] = res

            tasks = [run_one(sid, cfg) for sid, cfg in sources_config.items()]
            await asyncio.gather(*tasks)

        # Generate report like base class
        return self._generate_collection_report(source_results)
