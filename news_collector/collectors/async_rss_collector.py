import asyncio
import time
import aiohttp
import feedparser
import hashlib
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING
from aiohttp import ClientTimeout

from .rss_collector import RSSCollector
from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from urllib.parse import urlparse

if TYPE_CHECKING:
    from news_collector.utils.logger import NewsCollectorLogger

class AsyncRSSCollector(RSSCollector):
    """
    Colector RSS Asíncrono.
    Hereda de RSSCollector para reutilizar lógica de parsing y procesamiento,
    pero reimplementa la fase de I/O (fetching) usando aiohttp.
    """
    
    def __init__(self, logger_factory: Optional["NewsCollectorLogger"] = None) -> None:
        super().__init__(logger_factory=logger_factory)
        # We don't initialize self.session here as aiohttp requires loop context.
        # We'll use a session per batch or ad-hoc. 
        # For efficiency, we should probably share a session across the batch.
        # But BaseCollector orchestrates per-source calls.
        # In `collect_from_multiple_sources_async`, we just spawn tasks.
        # Ideally, we should pass a session, but BaseCollector signature doesn't support it strictly.
        # We will create a session inside collect_from_multiple_sources_async if we override it, 
        # OR just create one session per request (less efficient but functionally async).
        # BETTER: Override collect_from_multiple_sources_async to create the session once.
        pass

    async def collect_from_multiple_sources_async(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrate async collection sharing a single aiohttp session.
        """
        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        from datetime import datetime, timezone
        self.start_time = datetime.now(timezone.utc)
        self._emit_initial_batch_log(len(sources_config))
        self._reset_stats()
        
        # Configure shared session
        timeout = ClientTimeout(total=COLLECTION_CONFIG["request_timeout"])
        headers = {
            "User-Agent": COLLECTION_CONFIG["user_agent"],
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }
        
        connector = aiohttp.TCPConnector(limit=50) # Limit concurrent connections

        async with aiohttp.ClientSession(connector=connector, headers=headers, timeout=timeout) as session:
            tasks = []
            for source_id, source_config in sources_config.items():
                tasks.append(
                    self._process_single_source_async_with_session(
                        source_id, source_config, session
                    )
                )
            
            # Execute all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Consolidate results logic (same as BaseCollector but needed to be here to wrap session)
        source_results = {}
        for source_id, result in zip(sources_config.keys(), results):
            if isinstance(result, Exception):
                error_res = self._create_error_result(source_id, result)
                source_results[source_id] = error_res
                self.stats["total_errors"] += 1
            else:
                 source_results[source_id] = result

        return self._finalize_collection_cycle(source_results)

    async def _process_single_source_async_with_session(self, source_id, source_config, session):
        try:
            self._pre_process_source(source_id, source_config)
            # Call our specific internal method that takes a session
            source_result = await self._collect_from_source_async_internal(source_id, source_config, session)
            self._update_global_stats(source_result)
            self._post_process_source(source_id, source_config, source_result)
            self._emit_source_log(source_id, source_result)
            return source_result
        except Exception as exc:
            return self._handle_source_exception(source_id, exc)
            
    # Override the interface method just in case it's called individually (will create its own session)
    async def collect_from_source_async(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
         async with aiohttp.ClientSession() as session:
             return await self._collect_from_source_async_internal(source_id, source_config, session)

    async def _collect_from_source_async_internal(
        self, source_id: str, source_config: Dict[str, Any], session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        """
        Logic similar to RSSCollector.collect_from_source but async.
        """
        start_time = time.time()
        stats = {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": None,
            "processing_time": 0,
        }

        try:
            # 1. Job Key / Deduplication
            job_key = self._make_job_key(source_id, source_config["url"])
            if self._is_duplicate_job(job_key):
                stats["success"] = True
                return stats
            self._register_job(job_key)

            # 2. Robots & Rate Limiting (Synchronous check is fine for now, or could make async)
            # For simplicity we reuse the sync robot check as it caches heavily.
            # Ideally we'd have an async robot checker but that's a larger refactor.
            # We will use to_thread for this to avoid blocking the loop.
            allowed, robots_delay = await asyncio.to_thread(self._respect_robots, source_config["url"])
            
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                return stats

            # 3. Fetch Feed
            feed_content, status_code = await self._fetch_feed_async(source_id, source_config["url"], session)
            
            if status_code == 304:
                stats["success"] = True
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            # 4. Parse Feed (CPU bound -> execute in thread)
            # feedparser is synchronous and can be slow for big feeds
            parsed_feed = await asyncio.to_thread(feedparser.parse, feed_content)

            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = f"Feed malformado: {parsed_feed.bozo_exception}"
                return stats

            # 5. Extract Articles
            # Reuse sync extraction logic
            raw_articles = await asyncio.to_thread(
                    self._extract_articles_from_feed, parsed_feed, source_config, source_id
            )
            
            stats["articles_found"] = len(raw_articles)
            if not raw_articles:
                stats["success"] = True
                return stats

            # 6. Process & Save Articles
            # This involves DB operations which are likely Sync (SQLAlchemy blocking).
            # We MUST run this in thread to avoid blocking the event loop.
            saved_count = 0
            # We can process articles in parallel if we want, but saving to DB might lock.
            # Safer to do sequential save per source, but in a thread.
            
            def process_batch():
                count = 0
                for raw in raw_articles:
                    try:
                        processed = self._process_article(raw, source_id, source_config)
                        if processed and self._save_article(processed):
                            count += 1
                    except Exception as e:
                        pass # Logged inside
                return count

            saved_count = await asyncio.to_thread(process_batch)

            stats["articles_saved"] = saved_count
            stats["success"] = True

        except Exception as exc:
            stats["error_message"] = str(exc)
            
        finally:
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)
        
        return stats

    async def _fetch_feed_async(
        self, source_id: str, feed_url: str, session: aiohttp.ClientSession
    ) -> Tuple[Optional[str], Optional[int]]:
        try:
             # Basic conditional get headers logic reused from Sync if possible,
             # but we need to access DB for metadata.
             # DB access is blocking.
             cached_headers = await asyncio.to_thread(
                 self.db_manager.get_source_feed_metadata, source_id
             )
             
             req_headers = {}
             if cached_headers.get("etag"):
                 req_headers["If-None-Match"] = cached_headers["etag"]
             if cached_headers.get("last_modified"):
                 req_headers["If-Modified-Since"] = cached_headers["last_modified"]

             async with session.get(feed_url, headers=req_headers) as response:
                 status = response.status
                 if status == 304:
                     return (None, 304)
                 
                 if status >= 400:
                     return (None, status)
                 
                 content = await response.read()
                 text = await response.text()
                 
                 # Metadata update logic (Sync DB access -> Thread)
                 etag = response.headers.get("ETag")
                 lm = response.headers.get("Last-Modified")
                 ch = hashlib.sha256(content).hexdigest()
                 
                 if cached_headers.get("content_hash") == ch:
                     await asyncio.to_thread(
                         self.db_manager.update_source_feed_metadata, 
                         source_id, etag=etag, last_modified=lm, content_hash=ch
                     )
                     return (None, 304)

                 await asyncio.to_thread(
                     self.db_manager.update_source_feed_metadata, 
                     source_id, etag=etag, last_modified=lm, content_hash=ch
                 )
                 
                 return (text, status)

        except Exception as e:
            # Logger call might be sync or async? our logger is sync.
            # self.module_logger is sync.
            # self._emit_log calls module_logger.info/error.
            # Safe to call, but it does I/O (file/stdout).
            # Technically blocking, but usually acceptable for logging. 
            self._emit_log("error", "collector.feed.fetch_async_error", source_id=source_id, details={"error": str(e)})
            return (None, None)
