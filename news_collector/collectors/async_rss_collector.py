
import asyncio
import time
import httpx
import feedparser
import hashlib
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING
from news_collector.utils.security import validate_url_safety as validate_url_safety_sync

from .rss_collector import RSSCollector
from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from urllib.parse import urlparse

if TYPE_CHECKING:
    from news_collector.utils.logger import NewsCollectorLogger

class AsyncRSSCollector(RSSCollector):
    """
    Colector RSS Asíncrono.
    Hereda de RSSCollector para reutilizar lógica de parsing y procesamiento,
    pero reimplementa la fase de I/O (fetching) usando httpx.
    """
    
    def __init__(self, logger_factory: Optional["NewsCollectorLogger"] = None) -> None:
        super().__init__(logger_factory=logger_factory)

    async def collect_from_multiple_sources_async(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrate async collection sharing a single httpx client.
        """
        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        from datetime import datetime, timezone
        self.start_time = datetime.now(timezone.utc)
        self._emit_initial_batch_log(len(sources_config))
        self._reset_stats()
        
        # Configure shared client
        timeout = httpx.Timeout(COLLECTION_CONFIG["request_timeout"], connect=10.0)
        headers = {
            "User-Agent": COLLECTION_CONFIG["user_agent"],
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }
        
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=50)

        async with httpx.AsyncClient(limits=limits, headers=headers, timeout=timeout, follow_redirects=True) as client:
            tasks = []
            for source_id, source_config in sources_config.items():
                tasks.append(
                    self._process_single_source_async_with_client(
                        source_id, source_config, client
                    )
                )
            
            # Execute all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Consolidate results logic
        source_results = {}
        for source_id, result in zip(sources_config.keys(), results):
            if isinstance(result, Exception):
                error_res = self._create_error_result(source_id, result)
                source_results[source_id] = error_res
                self.stats["total_errors"] += 1
            else:
                 source_results[source_id] = result

        return self._finalize_collection_cycle(source_results)

    async def _process_single_source_async_with_client(self, source_id, source_config, client):
        try:
            self._pre_process_source(source_id, source_config)
            # Call our specific internal method that takes a client
            source_result = await self._collect_from_source_async_internal(source_id, source_config, client)
            self._update_global_stats(source_result)
            self._post_process_source(source_id, source_config, source_result)
            self._emit_source_log(source_id, source_result)
            return source_result
        except Exception as exc:
            return self._handle_source_exception(source_id, exc)
            
    # Override the interface method just in case (e.g. tests)
    async def collect_from_source_async(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
         async with httpx.AsyncClient(follow_redirects=True) as client:
             return await self._collect_from_source_async_internal(source_id, source_config, client)

    async def _collect_from_source_async_internal(
        self, source_id: str, source_config: Dict[str, Any], client: httpx.AsyncClient
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
            url = source_config["url"]
            
            # --- P0 SECURITY FIX: SSRF PROTECTION ---
            # Validate URL safety before any request.
            # Since validation involves blocking DNS, we run it in a thread.
            await asyncio.to_thread(validate_url_safety_sync, url)
            # ----------------------------------------

            # 1. Job Key / Deduplication
            job_key = self._make_job_key(source_id, url)
            if self._is_duplicate_job(job_key):
                stats["success"] = True
                return stats
            self._register_job(job_key)

            # 2. Robots Or Rate Limiting
            allowed, robots_delay = await asyncio.to_thread(self._respect_robots, url)
            
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                return stats

            # 3. Fetch Feed
            feed_content, status_code = await self._fetch_feed_async(source_id, url, client)
            
            if status_code == 304:
                stats["success"] = True
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            # 4. Parse Feed (CPU bound -> execute in thread)
            parsed_feed = await asyncio.to_thread(feedparser.parse, feed_content)

            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = f"Feed malformado: {parsed_feed.bozo_exception}"
                return stats

            # 5. Extract Articles
            raw_articles = await asyncio.to_thread(
                    self._extract_articles_from_feed, parsed_feed, source_config, source_id
            )
            
            stats["articles_found"] = len(raw_articles)
            if not raw_articles:
                stats["success"] = True
                return stats

            # 6. Process & Save Articles
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
            # Catch validation errors too
            stats["error_message"] = str(exc)
            
        finally:
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)
        
        return stats

    async def _fetch_feed_async(
        self, source_id: str, feed_url: str, client: httpx.AsyncClient
    ) -> Tuple[Optional[str], Optional[int]]:
        try:
             # DB Access: Sync -> Thread
             cached_headers = await asyncio.to_thread(
                 self.db_manager.get_source_feed_metadata, source_id
             )
             
             req_headers = {}
             if cached_headers.get("etag"):
                 req_headers["If-None-Match"] = cached_headers["etag"]
             if cached_headers.get("last_modified"):
                 req_headers["If-Modified-Since"] = cached_headers["last_modified"]

             # SSRF-SAFE FETCH WITH REDIRECT VALIDATION
             current_url = feed_url
             redirect_count = 0
             max_redirects = 5
             
             while redirect_count <= max_redirects:
                 # Validate URL safety before request
                 await asyncio.to_thread(validate_url_safety_sync, current_url)
                 
                 # Manual request execution (no auto-follow)
                 response = await client.get(
                     current_url, 
                     headers=req_headers, 
                     follow_redirects=False
                 )
                 
                 status = response.status_code
                 
                 # Handle Redirects
                 if 300 <= status < 400:
                     redirect_count += 1
                     location = response.headers.get("Location")
                     if not location:
                         self._emit_log("error", "collector.feed.redirect_error", source_id=source_id, details={"error": "Redirect without Location header"})
                         return (None, None)
                     
                     # Resolving relative redirects if necessary
                     from urllib.parse import urljoin
                     current_url = urljoin(current_url, location)
                     
                     # Loop back to validate new URL
                     continue
                 
                 # Handle Success/Not Modified
                 if status == 304:
                     return (None, 304)
                 
                 if status >= 400:
                     return (None, status)
                 
                 # Valid response found
                 content = response.content # bytes
                 text = response.text    # str
                 
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
             
             self._emit_log("error", "collector.feed.too_many_redirects", source_id=source_id, details={"max": max_redirects})
             return (None, None)

        except Exception as e:
            self._emit_log("error", "collector.feed.fetch_async_error", source_id=source_id, details={"error": str(e)})
            return (None, None)
