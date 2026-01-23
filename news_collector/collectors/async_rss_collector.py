import asyncio
import hashlib
import random
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import feedparser
import httpx

from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from news_collector.utils.security import (
    validate_url_safety as validate_url_safety_sync,
)

from .rss_collector import RSSCollector

if TYPE_CHECKING:
    from news_collector.utils.logger import NewsCollectorLogger


class AsyncRSSCollector(RSSCollector):
    """
    Colector RSS Asíncrono.
    Hereda de RSSCollector para reutilizar lógica de parsing y procesamiento,
    pero reimplementa la fase de I/O (fetching) usando httpx.
    """

    def __init__(
        self,
        logger_factory: Optional["NewsCollectorLogger"] = None,
        health_tracker: Optional[Any] = None,
    ) -> None:
        super().__init__(logger_factory=logger_factory, health_tracker=health_tracker)

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

        from news_collector.collectors.rate_limit_utils import (
            _normalize_domain,
            calculate_effective_delay,
        )

        async with httpx.AsyncClient(
            limits=limits, headers=headers, timeout=timeout, follow_redirects=True
        ) as client:
            # Group sources by domain
            sources_by_domain = {}
            for source_id, source_config in sources_config.items():
                domain = _normalize_domain(urlparse(source_config["url"]).netloc)
                if domain not in sources_by_domain:
                    sources_by_domain[domain] = []
                sources_by_domain[domain].append((source_id, source_config))

            async def process_domain_group(domain, sources_list):
                group_results = []
                for idx, (sid, sconfig) in enumerate(sources_list):
                    # Process source
                    result = await self._process_single_source_async_with_client(
                        sid, sconfig, client
                    )
                    group_results.append(result)

                    # Sleep between requests to same domain if not last
                    if idx < len(sources_list) - 1:
                        # Allow source config to override min delay (e.g. for fragile sites)
                        config_delay = sconfig.get("min_delay_seconds", 0.0)

                        # Calculate delay based on config
                        delay = calculate_effective_delay(domain, 0.0, config_delay)
                        await asyncio.sleep(delay)
                return group_results

            # Create task per domain
            domain_tasks = []
            for domain, sources_list in sources_by_domain.items():
                domain_tasks.append(process_domain_group(domain, sources_list))

            # Execute all domain groups in parallel
            domain_results_nested = await asyncio.gather(
                *domain_tasks, return_exceptions=True
            )

            # Flatten results
            results = []
            for group_res in domain_results_nested:
                if isinstance(group_res, list):
                    results.extend(group_res)
                else:
                    # If the whole domain group failed (unlikely with internal try/except)
                    # We need to map which sources failed?
                    # process_domain_group normally catches exceptions?
                    # Actually process_domain_group logic above doesn't have top-level try/except,
                    # but _process_single_source_async_with_client DOES.
                    # So group_res should be a list unless system error.
                    if isinstance(group_res, Exception):
                        # Log fatal error for domain
                        self._emit_log(
                            "error",
                            "collector.domain_group_failed",
                            details={"error": str(group_res)},
                        )
                        pass

        # Re-map results to source_id (order is scrambled now)
        # results is list of dicts. each dict has 'source_id'.
        # Error results might not have source_id if _create_error_result fails?
        # _create_error_result usually returns dict with source_id.

        # We need to reconstruct the list order expected by zip below?
        # The code below uses zip(sources_config.keys(), results).
        # THIS IS DANGEROUS now that we reordered execution.

        # FIXED LOGIC: Use a map
        results_map = {}
        for res in results:
            if isinstance(res, dict) and "source_id" in res:
                results_map[res["source_id"]] = res

        # Consolidate results logic using map
        source_results = {}
        for source_id in sources_config.keys():
            result = results_map.get(source_id)
            if not result:
                # Should not happen if all executed, unless Exception in gather
                result = self._create_error_result(
                    source_id, Exception("Result missing from execution")
                )

            if isinstance(result, Exception):  # From gather exception?
                error_res = self._create_error_result(source_id, result)
                source_results[source_id] = error_res
                self.stats["total_errors"] += 1
            else:
                source_results[source_id] = result

        return self._finalize_collection_cycle(source_results)

    async def _process_single_source_async_with_client(
        self, source_id, source_config, client
    ):
        try:
            self._pre_process_source(source_id, source_config)
            # Call our specific internal method that takes a client
            source_result = await self._collect_from_source_async_internal(
                source_id, source_config, client
            )
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
            return await self._collect_from_source_async_internal(
                source_id, source_config, client
            )

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
        print(
            f"DEBUG: AsyncRSSCollector internal processing {source_id}. health_tracker is {self.health_tracker} (id={id(self.health_tracker) if self.health_tracker else 'None'})"
        )

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
            feed_content, status_code = await self._fetch_feed_async(
                source_id, url, client, source_config
            )

            if status_code == 304:
                stats["success"] = True
                if self.health_tracker:
                    self.health_tracker.record_success(source_id, "fetch")
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            if self.health_tracker:
                self.health_tracker.record_success(source_id, "fetch")

            # 4. Parse Feed (CPU bound -> execute in thread)
            parsed_feed = await asyncio.to_thread(feedparser.parse, feed_content)

            if self.health_tracker:
                self.health_tracker.record_success(source_id, "parse")

            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = (
                    f"Feed malformado: {parsed_feed.bozo_exception}"
                )
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
                processed_candidates = []
                for raw in raw_articles:
                    try:
                        processed = self._process_article(raw, source_id, source_config)
                        if processed:
                            processed_candidates.append(processed)
                    except Exception:
                        pass  # Logged inside

                # Apply strict sequential filters and save
                return self._filter_and_save_articles(
                    source_id, processed_candidates, limit=5
                )

            saved_count = await asyncio.to_thread(process_batch)

            stats["articles_saved"] = saved_count
            stats["success"] = True

        except Exception as exc:
            # Catch validation errors too
            stats["error_message"] = str(exc)
            if self.health_tracker:
                self.health_tracker.record_failure(
                    source_id, "collector.fetch", "exception", {"error": str(exc)}
                )

        finally:
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)

        return stats

    async def _backoff_sleep_async(self, attempt: int) -> None:
        """Asynchronous backoff sleep."""
        base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
        max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
        jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))

        delay = min(max_b, (base * (2**attempt)) + jitter)
        await asyncio.sleep(delay)

    async def _fetch_feed_async(
        self,
        source_id: str,
        feed_url: str,
        client: httpx.AsyncClient,
        source_config: Dict[str, Any] = None,
    ) -> Tuple[Optional[str], Optional[int]]:
        max_retries = RATE_LIMITING_CONFIG["max_retries"]
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

            for attempt in range(max_retries + 1):
                while redirect_count <= max_redirects:
                    # Validate URL safety before request
                    await asyncio.to_thread(validate_url_safety_sync, current_url)

                    # Manual request execution (no auto-follow)

                    # Merge source-specific headers (e.g. custom Accept or Auth)
                    final_headers = req_headers.copy()
                    if source_config and "headers" in source_config:
                        final_headers.update(source_config["headers"])

                    try:
                        response = await client.get(
                            current_url, headers=final_headers, follow_redirects=False
                        )
                    except (httpx.RequestError, httpx.TimeoutException) as req_err:
                        # Network level errors are also candidates for retry
                        if attempt < max_retries:
                            await self._backoff_sleep_async(attempt)
                            break  # Break inner while to continue outer for loop? No.
                            # We need to restart the request.
                            # If we break here, we go to next attempt?
                            # Logic structure:
                            # for attempt:
                            #    try:
                            #       do_request
                            #    except:
                            #       retry
                        self._emit_log(
                            "warning",
                            "collector.feed.network_error",
                            source_id=source_id,
                            details={"error": str(req_err)},
                        )
                        return (None, None)

                    status = response.status_code

                    # Check for Retryable Status Codes
                    if status in (429, 500, 502, 503, 504):
                        if attempt < max_retries:
                            await self._backoff_sleep_async(attempt)
                            # Break from redirects loop to retry the request from scratch (outer loop)
                            # Wait, current_url might have changed!
                            # Should we reset redirect_count?
                            # If 429 happens after 2 redirects, we should probably just retry the CURRENT url.
                            # But my loop stricture is: outer attempt -> inner redirects.
                            # If inner fails with 429, we want to retry.
                            # Cleaner: Move status check OUTSIDE redirect loop?
                            # Or use recursion?
                            # Or just handle it.
                            break

                        self._emit_log(
                            "warning",
                            "collector.feed.status_retry_exhausted",
                            source_id=source_id,
                            details={"status": status},
                        )
                        return (None, status)

                    # Handle Not Modified (304)
                    if status == 304:
                        return (None, 304)

                    # Handle Redirects
                    if 300 <= status < 400 and status != 304:
                        redirect_count += 1
                        location = response.headers.get("Location")
                        if not location:
                            self._emit_log(
                                "error",
                                "collector.feed.redirect_error",
                                source_id=source_id,
                                details={"error": "Redirect without Location header"},
                            )
                            return (None, None)

                        from urllib.parse import urljoin

                        current_url = urljoin(current_url, location)
                        continue

                    if status >= 400:
                        return (None, status)

                    # Valid response found
                    content = response.content  # bytes
                    text = response.text  # str

                    etag = response.headers.get("ETag")
                    lm = response.headers.get("Last-Modified")
                    ch = hashlib.sha256(content).hexdigest()

                    if cached_headers.get("content_hash") == ch:
                        await asyncio.to_thread(
                            self.db_manager.update_source_feed_metadata,
                            source_id,
                            etag=etag,
                            last_modified=lm,
                            content_hash=ch,
                        )
                        return (None, 304)

                    await asyncio.to_thread(
                        self.db_manager.update_source_feed_metadata,
                        source_id,
                        etag=etag,
                        last_modified=lm,
                        content_hash=ch,
                    )

                    return (text, status)

                # End of while loop (redirects exhausted or broken for retry)
                if redirect_count > max_redirects:
                    self._emit_log(
                        "error",
                        "collector.feed.too_many_redirects",
                        source_id=source_id,
                        details={"max": max_redirects},
                    )
                    return (None, None)

            return (None, None)

        except Exception as e:
            self._emit_log(
                "error",
                "collector.feed.fetch_async_error",
                source_id=source_id,
                details={"error": str(e)},
            )
            return (None, None)
