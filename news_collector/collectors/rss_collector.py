# src/collectors/rss_collector.py
# Colector RSS para News Collector System
# ======================================

"""
Este es el corazón palpitante de nuestro sistema de recopilación de noticias.
Es como un explorador digital súper inteligente que sabe exactamente dónde buscar
las mejores noticias científicas, cómo obtenerlas de manera respetuosa, y cómo
traerte solo la información más relevante y bien estructurada.

La filosofía aquí es ser un "buen ciudadano" de internet: respetar los rate limits,
manejar errores graciosamente, y siempre dejar los servidores mejor de como los
encontramos (o al menos no peor).
"""

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict
from urllib.parse import urlparse

import feedparser
import requests

from news_collector.utils.pydantic_compat import get_pydantic_module

ValidationError = get_pydantic_module().ValidationError


from news_collector.config.settings import COLLECTION_CONFIG
from news_collector.contracts import CollectorArticleModel
from news_collector.enrichment import enrichment_pipeline
from news_collector.logic.parsers.image_extractor import ImageCandidate, ImageExtractor
from news_collector.logic.parsers.rss_parser import RssParser
from news_collector.scoring.pre_scorer import PreScorer
from news_collector.utils.url_canonicalizer import configure_canonicalization_cache

from .base_collector import BaseCollector

if TYPE_CHECKING:  # pragma: no cover - typing only
    from news_collector.utils.logger import NewsCollectorLogger


configure_canonicalization_cache(
    int(COLLECTION_CONFIG.get("canonicalization_cache_size", 0))
)


class RSSCollector(BaseCollector):
    """
    Colector especializado en feeds RSS y Atom.

    Esta clase es como un bibliotecario especializado que conoce íntimamente
    el lenguaje de los feeds RSS, sabe cómo extraer la información más valiosa
    de cada uno, y puede adaptarse a las particularidades de diferentes fuentes.

    Hereda de BaseCollector para mantener consistencia con otros tipos de
    colectores que podríamos agregar en el futuro (APIs, web scraping, etc.).
    """

    # Robust Headers for Feed Fetching (Browser-like to avoid 403s)
    # NOTE: Removed 'br' (Brotli) because if the python environment lacks the brotli package,
    # requests won't decode it automatically, leading to binary garbage.
    FEED_REQUEST_headers = {
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.7",
        # User-Agent is handled by the client/config, but we ensure it's set there.
    }

    def __init__(
        self,
        logger_factory: Optional["NewsCollectorLogger"] = None,
        health_tracker: Optional[Any] = None,
    ) -> None:
        super().__init__(logger_factory=logger_factory, health_tracker=health_tracker)
        # Replaced manual session with RobustRequestsClient
        from news_collector.infrastructure.requests_client import RobustRequestsClient

        self.client = RobustRequestsClient()
        # Expose session object for backward compatibility with ImageExtractor if needed
        # (ImageExtractor takes a session, we can pass self.client.session)
        self.session = self.client.session

        self.pre_scorer = PreScorer()
        self.parser = RssParser()
        self.image_extractor = ImageExtractor(session=self.session)

        # Scholarly Enrichment
        from news_collector.enrichment.scholarly import ScholarlyMetadataEnricher

        self.scholarly_enricher = ScholarlyMetadataEnricher()

        # Enrichment Strategy Router
        from news_collector.enrichment.router import EnrichmentStrategyRouter

        self.router = EnrichmentStrategyRouter(logger_factory=logger_factory)
        # Stable replay seam for deterministic fixture-driven smoke/profile runs.
        self._feed_replay_source = None

        # Estadísticas de la sesión actual
        self.session_stats: RSSCollector._SessionStats = {
            "sources_checked": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "errors_encountered": 0,
            "start_time": datetime.now(timezone.utc),
        }

    def _create_session(self):
        """Deprecated: Internal session is managed by RobustRequestsClient."""
        pass

    def set_feed_replay_source(self, replay_source: Any | None) -> None:
        """
        Stable replay seam to inject deterministic feed fetch responses.
        When set, collect_from_source bypasses robots/rate-limit network checks.
        """
        self._feed_replay_source = replay_source

    def _fetch_feed_content(
        self, feed_url: str, request_headers: Dict[str, str]
    ) -> requests.Response:
        """Helper to fetch using robust client."""
        return self.client.get(feed_url, headers=request_headers)

    # ... (collect_from_source logic mostly remains, but we need to update the fetching parts) ...
    # Wait, I cannot easily replace the ENTIRE logic in one go without errors.
    # I should target the SPECIFIC blocks that do fetching.

    # 1. Update _fetch_feed to use self.client.get
    # 2. Update the full text fetch loop to use self.client.get and check fetch_mode

    # Let's perform surgical edits using multi_replace first.
    # I will cancel this Replace and use MultiReplace.

    def collect_from_source(  # noqa: C901
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Recopila artículos de una fuente RSS específica.

        Este método es como enviar a nuestro explorador a una biblioteca específica
        con instrucciones precisas sobre qué tipo de libros buscar y cómo traerlos
        de vuelta de manera organizada.

        Args:
            source_id: Identificador único de la fuente
            source_config: Configuración completa de la fuente

        Returns:
            Diccionario con estadísticas de la recolección
        """
        start_time = time.time()
        stats = {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": None,
            "processing_time": 0,
            "content_mode": source_config.get("content_mode", "full_text"),
        }

        try:
            # 0a. Skip permanently blocked sources
            if source_config.get("status") == "blocked":
                self._emit_log(
                    "info",
                    "collector.source.blocked",
                    source_id=source_id,
                    details={"reason": "Source marked as blocked in config"},
                )
                stats["success"] = True
                stats["error_message"] = "Source blocked in config"
                return stats

            # 0b. Circuit Breaker Check (MVS)
            # Feature Flag: Kill Switch
            if os.getenv("ENABLE_CIRCUIT_BREAKER", "true").lower() != "false":
                circuit_state = self.db_manager.get_source_circuit_state(source_id)
                if circuit_state:
                    next_retry = circuit_state.get("next_retry_at")
                    # Ensure timezone awareness for comparison (SQLite may return naive)
                    if next_retry and next_retry.tzinfo is None:
                        next_retry = next_retry.replace(tzinfo=timezone.utc)

                    if (
                        circuit_state.get("status") == "COOLDOWN"
                        and next_retry
                        and next_retry > datetime.now(timezone.utc)
                    ):
                        self._emit_log(
                            "info",
                            "collector.circuit_breaker.skip",
                            source_id=source_id,
                            details={
                                "reason": "COOLDOWN",
                                "retry_at": circuit_state["next_retry_at"].isoformat(),
                            },
                        )
                        stats["success"] = True
                        stats["error_message"] = "Circuit Breaker: Skipped (Cooldown)"
                        return stats

            job_key = self._make_job_key(source_id, source_config["url"])
            if self._is_duplicate_job(job_key):
                self._emit_log(
                    "info",
                    "collector.job.duplicate",
                    source_id=source_id,
                    details={"url": source_config.get("url")},
                )
                stats["success"] = True
                return stats

            self._register_job(job_key)
            self._emit_log(
                "info",
                "collector.fetch.start",
                source_id=source_id,
                details={
                    "source_name": source_config.get("name"),
                    "url": source_config.get("url"),
                },
            )

            if self._feed_replay_source is None:
                allowed, robots_delay = self._respect_robots(source_config["url"])
                if not allowed:
                    stats["error_message"] = "Bloqueado por robots.txt"
                    self._emit_log(
                        "warning",
                        "collector.fetch.blocked_robots",
                        source_id=source_id,
                        details={"url": source_config.get("url")},
                    )
                    self._send_to_dlq(
                        source_id, source_config["url"], "robots_disallowed"
                    )
                    return stats

                domain = urlparse(source_config["url"]).netloc
                self._enforce_domain_rate_limit(
                    domain, robots_delay, source_config.get("min_delay_seconds")
                )

            # 1. Robust Fetch
            feed_response = self._fetch_feed_robust(source_id, source_config)

            if not feed_response["success"]:
                stats["success"] = False  # Explicitly false if fetch failed
                stats["error_message"] = feed_response.get("error_message")
                # Already logged in fetch_robust
                return stats

            if feed_response.get("status_code") == 304:
                stats["success"] = True
                return stats

            # 2. Robust Parse
            parse_result = self._parse_feed_robust(
                source_id, feed_response["content"], feed_response["url"], source_config
            )

            if not parse_result["success"]:
                stats["error_message"] = parse_result.get("error_message")
                # Classification logic is inside parse_robust
                return stats

            parsed_feed = parse_result["parsed_feed"]

            # 3. Extract Articles
            raw_articles = self._extract_articles_from_feed(
                parsed_feed, source_config, source_id
            )
            print(
                f"DEBUG: RSSCollector source={source_id} raw_articles={len(raw_articles)}",
                flush=True,
            )
            stats["articles_found"] = len(raw_articles)

            if not raw_articles:
                self._emit_log(
                    "info",
                    "collector.feed.empty",
                    source_id=source_id,
                    details={"url": source_config.get("url")},
                )
                stats["success"] = True
                return stats

            if self.health_tracker:
                self.health_tracker.record_success(source_id, "fetch")
                self.health_tracker.record_success(source_id, "parse")

            # Batch process candidates for filtering pipeline
            processed_candidates = []
            for raw_article in raw_articles:
                try:
                    processed_article = self._process_article(
                        raw_article, source_id, source_config
                    )
                    if processed_article:
                        processed_candidates.append(processed_article)
                except Exception as exc:
                    self._emit_log(
                        "error",
                        "collector.article.process_error",
                        source_id=source_id,
                        details={
                            "error": str(exc),
                            "url": raw_article.get("link")
                            or raw_article.get("id")
                            or raw_article.get("url"),
                        },
                    )
                    self.session_stats["errors_encountered"] += 1

            # Apply strict sequential filters and save
            saved_count = self._filter_and_save_articles(
                source_id, processed_candidates, limit=5
            )
            stats["articles_saved"] = saved_count
            stats["success"] = True

            elapsed = time.time() - start_time
            self._emit_log(
                "info",
                "collector.fetch.completed",
                source_id=source_id,
                latency=elapsed,
                details={
                    "articles_found": len(raw_articles),
                    "articles_saved": saved_count,
                    "feed_type": parse_result.get("feed_type", "unknown"),
                },
            )

        except requests.RequestException as exc:
            stats["error_message"] = f"Error de red general: {exc}"
            self._emit_log(
                "error",
                "collector.fetch.network_error",
                source_id=source_id,
                details={"error": str(exc), "url": source_config.get("url")},
            )
            if self.health_tracker:
                self.health_tracker.record_failure(
                    source_id, "collector.fetch", "network_error", {"error": str(exc)}
                )

        except Exception as exc:
            stats["error_message"] = f"Error inesperado: {exc}"
            self._emit_log(
                "error",
                "collector.fetch.unexpected_error",
                source_id=source_id,
                details={"error": str(exc)},
            )
            if self.health_tracker:
                self.health_tracker.record_failure(
                    source_id,
                    "collector.fetch",
                    "unexpected_error",
                    {"error": str(exc)},
                )

        finally:
            # Update Circuit Breaker State
            try:
                self.db_manager.update_source_circuit_state(
                    source_id,
                    success=stats["success"],
                    error_message=stats.get("error_message"),
                )
            except Exception as e:
                self._emit_log(
                    "error",
                    "collector.circuit_breaker.update_failed",
                    source_id=source_id,
                    details={"error": str(e)},
                )

            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)
            self.session_stats["sources_checked"] += 1
            self.session_stats["articles_found"] += stats["articles_found"]
            self.session_stats["articles_saved"] += stats["articles_saved"]

        return stats

    def _fetch_feed(self, source_id: str, feed_url: str) -> tuple[Optional[str], int]:
        """
        Legacy integration shim for older tests and external callers.
        Delegates completely to `_fetch_feed_robust`.
        """
        source_config = {"url": feed_url}
        result = self._fetch_feed_robust(source_id, source_config)
        content_bytes = result.get("content")
        content_text = None
        if content_bytes is not None:
            try:
                content_text = content_bytes.decode(result.get("encoding") or "utf-8")
            except UnicodeDecodeError:
                content_text = content_bytes.decode("utf-8", errors="replace")
        return content_text, result.get("status_code", 500)

    def _fetch_feed_robust(  # noqa: C901
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fetches feed content with robust handling for bytes, headers, and status codes.
        Returns a dict with success, status_code, content (bytes), url, and error_message.
        """
        url = source_config["url"]

        # 1. Check Metadata for Conditional Get
        cached_headers: Dict[str, Optional[str]] = {}
        try:
            meta = self.db_manager.get_source_feed_metadata(source_id)
            if meta:
                cached_headers = meta
        except Exception as e:
            self._emit_log(
                "debug",
                "collector.feed.metadata_fetch_failed",
                source_id=source_id,
                details={"error": str(e)},
            )

        request_headers = self.FEED_REQUEST_headers.copy()
        etag = cached_headers.get("etag")
        if etag:
            request_headers["If-None-Match"] = etag
        last_modified = cached_headers.get("last_modified")
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified

        if source_config.get("headers"):
            request_headers.update(source_config["headers"])

        if self._feed_replay_source is not None:
            try:
                return self._feed_replay_source.fetch_feed(
                    source_id=source_id,
                    source_config=source_config,
                    cached_headers=cached_headers,
                    request_headers=request_headers,
                    db_manager=self.db_manager,
                )
            except Exception as e:
                return {
                    "success": False,
                    "error_message": f"Replay Error: {str(e)}",
                    "url": url,
                }

        # curl_cffi path for sources behind Cloudflare/WAF
        if source_config.get("use_curl_cffi"):
            try:
                from scrapling import Fetcher

                start_t = time.perf_counter()
                page = Fetcher.get(
                    url,
                    headers=request_headers,
                    timeout=COLLECTION_CONFIG.get("request_timeout", 30),
                    follow_redirects=True,
                )
                latency = (time.perf_counter() - start_t) * 1000

                body_bytes = (
                    page.body.encode("utf-8")
                    if isinstance(page.body, str)
                    else page.body
                )
                status = page.status if hasattr(page, "status") else 200

                self._emit_log(
                    "debug",
                    "collector.fetch.raw",
                    source_id=source_id,
                    details={
                        "status": status,
                        "bytes": len(body_bytes),
                        "client": "curl_cffi",
                        "latency_ms": latency,
                    },
                )

                if status >= 400:
                    return {
                        "success": False,
                        "status_code": status,
                        "error_message": f"HTTP {status}",
                        "url": url,
                    }
                if len(body_bytes) > 10 * 1024 * 1024:
                    return {
                        "success": False,
                        "error_message": "Feed too large (>10MB)",
                        "url": url,
                    }

                return {
                    "success": True,
                    "status_code": status,
                    "content": body_bytes,
                    "url": url,
                    "encoding": "utf-8",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error_message": f"curl_cffi Error: {str(e)}",
                    "url": url,
                }

        try:
            start_t = time.perf_counter()
            response = self.client.get(
                url,
                headers=request_headers,
                timeout=COLLECTION_CONFIG.get("request_timeout", 30),
            )
            latency = (time.perf_counter() - start_t) * 1000

            # Log raw fetch details for observability
            self._emit_log(
                "debug",
                "collector.fetch.raw",
                source_id=source_id,
                details={
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "content_type": response.headers.get("Content-Type", ""),
                    "latency_ms": latency,
                },
            )

            # 2. Handle Status Codes
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                self._emit_log(
                    "warning",
                    "collector.feed.suspicious_content_type",
                    source_id=source_id,
                    details={"content_type": content_type, "url": url},
                )

            if response.status_code == 304:
                # Sometimes 304 is returned but we might want to force refresh if local cache invalid?
                # Optimization: 304 means success but no new content. Update metadata timestamp.
                try:
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_hash=cached_headers.get("content_hash"),
                    )
                except Exception as e:
                    self._emit_log(
                        "warning",
                        "collector.feed.metadata_update_failed",
                        source_id=source_id,
                        details={"error": str(e), "context": "304_response"},
                    )
                return {
                    "success": True,
                    "status_code": 304,
                    "content": None,
                    "url": url,
                }

            if response.status_code >= 400:
                self._emit_log(
                    "warning",
                    "collector.fetch.error",
                    source_id=source_id,
                    details={"status": response.status_code, "url": url},
                )
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error_message": f"HTTP {response.status_code}",
                    "url": url,
                }

            # 3. Content Size Check
            if len(response.content) > 10 * 1024 * 1024:
                return {
                    "success": False,
                    "error_message": "Feed too large (>10MB)",
                    "url": url,
                }

            # 4. Success - Return Content
            # Handle ETag updates
            content_hash = hashlib.sha256(response.content).hexdigest()

            if cached_headers.get("content_hash") == content_hash:
                self._emit_log(
                    "info", "collector.feed.content_unchanged", source_id=source_id
                )
                # Update metadata timestamp even if 304-equivalent
                try:
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_hash=content_hash,
                    )
                except Exception as e:
                    self._emit_log(
                        "warning",
                        "collector.feed.metadata_update_failed",
                        source_id=source_id,
                        details={"error": str(e), "context": "content_unchanged"},
                    )
                return {
                    "success": True,
                    "status_code": 304,
                    "content": None,
                    "url": url,
                }  # Treat as 304 logic upstream

            # Save metadata
            try:
                self.db_manager.update_source_feed_metadata(
                    source_id,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    content_hash=content_hash,
                )
            except Exception as e:
                self._emit_log(
                    "warning",
                    "collector.feed.metadata_update_failed",
                    source_id=source_id,
                    details={"error": str(e), "context": "new_content"},
                )

            return {
                "success": True,
                "status_code": response.status_code,
                "content": response.content,  # Return BYTES
                "url": url,
                "encoding": getattr(response, "encoding", None),
            }

        except requests.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", 500)
            return {
                "success": False,
                "status_code": status,
                "error_message": f"Network Error: {str(e)}",
                "url": url,
            }
        except Exception as e:
            return {
                "success": False,
                "error_message": f"Unexpected Error: {str(e)}",
                "url": url,
            }

    def _parse_feed_robust(
        self, source_id: str, content: bytes, url: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parses feed content (bytes) with robust error classification.
        Detects HTML blocks, JSON, and tries standard parsing.
        """
        # 1. Sniff Content Type
        content_prefix = content[:1000].strip().lower()

        # Check for HTML (Blocked/AuthWall/Splash)
        # Look for <html, <!doctype html, or specific block text
        html_indicators = [
            b"<html",
            b"<!doctype html",
            b"<body",
            b"cloudflare",
            b"please enable cookies",
            b"captcha",
            b"<head",
        ]

        if any(ind in content_prefix for ind in html_indicators):
            self._emit_log(
                "warning",
                "collector.feed.classified_as_html",
                source_id=source_id,
                details={"prefix": str(content_prefix[:200])},  # Log more for debug
            )
            return {
                "success": False,
                "error_message": "Feed blocked/invalid (HTML Response)",
                "classification": "BLOCKED_OR_NOT_FEED",
            }

        # Check for JSON
        if content_prefix.startswith(b"{") or content_prefix.startswith(b"["):
            # For now, we don't support JSON feeds standard implementation unless feedparser handles it?
            # Feedparser DOES support JSON Feed (v1). So let's try to parse it,
            # but if it fails, classify clearly.
            pass

        # 2. Parse
        # Pass bytes directly to feedparser to let it handle encoding sniffing
        parsed = feedparser.parse(content)

        # 3. Analyze Bozo
        if parsed.bozo:
            # Tolerant Check
            if self._is_acceptable_bozo(parsed):
                pass  # Continue
            else:
                exc = parsed.get("bozo_exception")
                # Secondary check: if it failed and content looks like HTML
                self._emit_log(
                    "warning",
                    "collector.feed.parse_error_debug",
                    source_id=source_id,
                    details={
                        "error": str(exc),
                        "prefix_hex": content[:100].hex(),
                        "prefix_repr": repr(content[:100]),
                    },
                )
                return {
                    "success": False,
                    "error_message": f"Malformed Feed: {exc}",
                    "classification": "MALFORMED_XML",
                }

        # 4. Check for Empty Entries + Feed Index?
        if not parsed.entries:
            # Could be a feed index (OPML or similar list of feeds)? Or just empty.
            # Implementation of Feed Index detection would go here.
            pass

        return {
            "success": True,
            "parsed_feed": parsed,
            "feed_type": getattr(parsed, "version", "unknown"),
        }

    def _is_acceptable_bozo(self, parsed_feed) -> bool:
        return self.parser.is_acceptable_bozo(parsed_feed)

    def _extract_articles_from_feed(  # noqa: C901
        self,
        parsed_feed,
        source_config: Dict[str, Any],
        source_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Extrae artículos usando el RssParser logic.
        """
        # Fetch multiplier logic is now implicit since parser returns all valid items,
        # but we effectively just get candidates.

        candidates = self.parser.extract_items(parsed_feed, source_config)

        # We need to filter by recent_days_threshold and duplication here (Collector responsibility)
        filtered_candidates = []
        datetime.now(timezone.utc) - timedelta(
            days=COLLECTION_CONFIG["recent_days_threshold"]
        )

        max_articles = COLLECTION_CONFIG["max_articles_per_source"]
        candidate_multiplier = 4
        fetch_limit = max_articles * candidate_multiplier

        count = 0
        for cand in candidates:
            if count >= fetch_limit:
                break

            # Date filter
            # if cand.get("published_date") and cand["published_date"] < recent_threshold:
            #     continue

            # Duplicate filter
            if self.db_manager.article_exists(cand["url"]):
                continue

            filtered_candidates.append(cand)
            count += 1

        # The rest of the logic (PreScorer, Full Text) remains in collect_from_source loop
        # Wait, collect_from_source calls this method to get 'raw_articles'.
        # And then it iterates 'raw_articles', calls _process_article.
        # But _process_article duplicates some logic?

        # Let's return the candidates. The original method also did PreScoring?
        # Yes, original method at lines 656+ called PreScorer internally!
        # I must preserve that logic.

        candidates = filtered_candidates

        if len(candidates) > max_articles:
            self._emit_log(
                "info",
                "collector.prescorer.ranking_start",
                details={"candidates": len(candidates), "limit": max_articles},
            )

            # --- START PRESCORER UPDATE ---
            # If default LLM is not configured, use heuristic scoring
            if self.pre_scorer.model_name == "ollama":  # Default placeholder check
                # Heuristic backup: Prefers longer summaries and content (if available)
                # Sort by length of summary descending
                candidates.sort(
                    key=lambda x: len(x.get("summary", "") or ""), reverse=True
                )
                selected_candidates = candidates[:max_articles]
                self._emit_log(
                    "info",
                    "collector.prescorer.heuristic_fallback",
                    details={"method": "length_sort"},
                )
            else:
                selected_candidates = self.pre_scorer.select_top_candidates(
                    candidates,
                    limit=max_articles,
                    source_context=source_config.get("name", source_id),
                )
            # --- END PRESCORER UPDATE ---
        else:
            selected_candidates = candidates

        # 3. PHASE THREE: Deep Processing (Full Text & Image Extraction)
        articles = []

        # or rely on the ImageExtractor to fetch if provided a URL (but avoiding double fetch if possible).
        # Optimization: We'll fetch the content ONCE here, pass to both extractors.

        for cand in selected_candidates:
            try:
                cand.setdefault(
                    "content_mode", source_config.get("content_mode", "full_text")
                )
                # --- ENRICHMENT STRATEGY ROUTER ---
                enrichment_result = self.router.route_enrichment(
                    source_id, source_config, cand
                )

                cand["content"] = enrichment_result.get("content", "")
                html_content = enrichment_result.get("raw_content") or ""

                # Metadata from Scholarly, etc.
                if enrichment_result.get("metadata"):
                    cand["enrichment_metadata"] = enrichment_result["metadata"]

                # Log strategy used
                if enrichment_result.get("strategy_used") != "none":
                    self._emit_log(
                        "info",
                        "enrichment.router.selected",
                        source_id=source_id,
                        details={
                            "url": cand.get("url"),
                            "strategy": enrichment_result.get("strategy_used"),
                            "success": enrichment_result.get("success"),
                            "reason": enrichment_result.get("reason"),
                        },
                    )

                # Fallback logic (Router handles strategies, but we still ensure content/summary logic)
                if not cand.get("content"):
                    cand["content"] = cand.get("summary", "")
                    # Mark as fallback so validation rules can be lenient
                    # BUT preserve 'summary_only' if explicitly configured of via discovery_only
                    effective_content_mode = cand.get(
                        "content_mode"
                    ) or source_config.get("content_mode", "full_text")
                    if cand["content"] and effective_content_mode != "summary_only":
                        cand["content_mode"] = "summary_fallback"

                # Image Extraction Logic
                image_status = "MISSING_SOURCE"
                image_source = None

                # 1. Check if feed provided an image
                feed_image = cand.get("image_url")
                if feed_image:
                    # Validate it
                    if self.image_extractor.validate_image(
                        ImageCandidate(url=str(feed_image), source="feed")
                    ):
                        image_status = "IMAGE_OK"
                        image_source = "feed"
                    else:
                        self._emit_log(
                            "info",
                            "collector.image.feed_image_rejected",
                            details={"url": feed_image},
                        )
                        feed_image = None  # discard invalid feed image

                # 2. If no valid feed image, try extraction from HTML
                if not feed_image and html_content:
                    image_candidates = self.image_extractor.extract_candidates(
                        html_content, cand["url"]
                    )
                    for img_cand in image_candidates:
                        if self.image_extractor.validate_image(img_cand):
                            cand["image_url"] = img_cand.url
                            image_status = "IMAGE_OK"
                            image_source = img_cand.source
                            break

                    if image_status != "IMAGE_OK":
                        if image_candidates:
                            image_status = "IMAGE_VALIDATION_FAILED"  # Found candidates but none valid
                        else:
                            image_status = "IMAGE_MISSING_SOURCE"  # No candidates found

                elif not feed_image and not html_content:
                    image_status = "IMAGE_DOWNLOAD_FAILED"

                # Add status to metadata
                if "article_metadata" not in cand:
                    cand["article_metadata"] = {}

                cand["_image_status"] = image_status
                cand["_image_source"] = image_source

                if "entry_ref" in cand:
                    del cand["entry_ref"]

                if self._validate_article_data(cand):
                    articles.append(cand)

            except Exception as e:
                self._emit_log(
                    "warning",
                    "collector.article.process_failed",
                    details={"error": str(e)},
                )
                continue

        return articles

    def _validate_article_data(self, article: Dict[str, Any]) -> bool:
        """Helper to validate minimal requirements before returning from extract."""
        if not article.get("url"):
            return False
        if not article.get("title"):  # noqa: SIM103
            return False
        return True

    def _process_article(  # noqa: C901
        self, raw_article: Dict[str, Any], source_id: str, source_config: Dict[str, Any]
    ) -> Optional[CollectorArticleModel]:
        """
        Procesa un artículo crudo para prepararlo para almacenamiento.

        Este método es como tener un editor experto que toma información
        en bruto y la transforma en un formato estándar, enriquecido
        y listo para análisis posterior.
        """
        try:
            # Validaciones básicas
            if not raw_article.get("url") or not raw_article.get("title"):
                return None

            # Crear estructura estándar del artículo
            processed_article = {
                "url": raw_article["url"],
                "title": raw_article["title"][:500],  # Limitar longitud del título
                "summary": raw_article.get("summary", "")[:2000],  # Limitar resumen
                "content": raw_article.get("content"),  # Full text content
                "source_id": source_id,
                "source_name": source_config["name"],
                "category": source_config["category"],
                "published_date": raw_article.get("published_date"),
                "published_tz_offset_minutes": raw_article.get(
                    "published_tz_offset_minutes"
                ),
                "published_tz_name": raw_article.get("published_tz_name"),
                "authors": raw_article.get("authors", []),
                "language": "en",  # será recalculado abajo
                "is_preprint": source_config.get("special_handling") == "preprint",
                "article_metadata": {
                    "source_metadata": raw_article.get("source_metadata", {}),
                    "credibility_score": source_config["credibility_score"],
                    "processing_timestamp": datetime.now(timezone.utc).isoformat(),
                    "original_url": raw_article.get("original_url", raw_article["url"]),
                    "image_url": raw_article.get("image_url"),
                    "image_status": raw_article.get("_image_status"),
                    "image_source": raw_article.get("_image_source"),
                },
                "content_mode": raw_article.get("content_mode", "full_text"),
                "min_summary_length_override": source_config.get("min_summary_length"),
                "min_content_length_override": source_config.get("min_content_length"),
            }

            # Extraer DOI si está disponible
            if raw_article.get("source_metadata", {}).get("doi"):
                processed_article["doi"] = raw_article["source_metadata"]["doi"]

            # Determinar journal si es posible
            feed_title = raw_article.get("source_metadata", {}).get("feed_title")
            if feed_title:
                processed_article["journal"] = feed_title

            # Calcular estadísticas básicas del texto
            content_text = processed_article.get("content") or ""
            content_for_stats = f"{processed_article['title']} {processed_article['summary']} {content_text}"
            processed_article["word_count"] = len(content_for_stats.split())
            processed_article["reading_time_minutes"] = max(
                1, processed_article["word_count"] // 200
            )

            if not processed_article["language"]:
                processed_article["language"] = "en"

            original_content = processed_article.get("content", "") or ""
            original_title = processed_article.get("title", "") or ""

            # --- 2. ENRICHMENT STRATEGY ROUTING ---
            enrichment_strategy = (
                COLLECTION_CONFIG.get("sources", {})
                .get(source_id, {})
                .get("enrichment_strategy")
            )

            # Temporary: Check if source_id in hardcoded list if config not loaded deep enough
            # (In production, config is loaded from yaml)

            is_scholarly = enrichment_strategy == "scholarly_metadata"

            if is_scholarly:
                # Use Scholarly Enricher (Crossref/Reference Metadata)
                url_to_enrich = processed_article.get("url", "")
                enrich_result = self.scholarly_enricher.enrich_url(url_to_enrich)

                if enrich_result["success"]:
                    processed_article["content"] = enrich_result["content"]
                    processed_article["title"] = (
                        enrich_result.get("title") or original_title
                    )
                    # Add metadata to existing dictionary if possible or create new field in model later
                    # For now, just ensuring content is high quality.

                    # Create minimal "enrichment" block to satisfy schema
                    processed_article["article_metadata"]["enrichment"] = {
                        "entities": [],
                        "topics": [],
                        "sentiment": "neutral",
                        "model_version": "scholarly_v1",
                        "normalized_title": processed_article["title"][:500],
                        "normalized_summary": processed_article["summary"][:2000],
                    }
                else:
                    # Failed scholarly enrichment
                    self._emit_log(
                        "warning",
                        "collector.enrichment.scholarly_failed",
                        source_id=source_id,
                        details={
                            "reason": enrich_result.get("reason"),
                            "url": url_to_enrich,
                        },
                    )
                    # Fallthrough might leave content short, which gets caught by Stage B
                    processed_article["article_metadata"]["enrichment"] = {
                        "language": processed_article.get("language", "en"),
                        "normalized_title": original_title[:500],
                        "normalized_summary": processed_article.get("summary", "")[
                            :2000
                        ],
                        "sentiment": "neutral",
                        "entities": [],
                        "topics": [],
                        "model_version": "scholarly_failed",
                        "error": enrich_result.get("reason"),
                    }

            else:
                # --- STANDARD ENRICHMENT (Web Scraping) ---
                try:
                    enrichment = enrichment_pipeline.enrich_article(
                        {
                            "title": original_title,
                            "summary": processed_article.get("summary", ""),
                            "content": original_content,
                            "language": processed_article.get("language", "en"),
                            "url": raw_article.get(
                                "url"
                            ),  # Passing URL might be useful if pipeline supports it in future or for logging, but model uses title/summary/content
                        }
                    )

                    if enrichment:
                        if enrichment.get("content"):
                            processed_article["content"] = enrichment["content"]
                        # Enrichment metadata is already captured in article_metadata.enrichment;
                        # do NOT set top-level extra keys (CRIT-03: extra="forbid").
                        if enrichment.get("language"):
                            processed_article["language"] = enrichment.get("language")
                        if enrichment.get("reading_time_minutes"):
                            processed_article["reading_time_minutes"] = enrichment.get(
                                "reading_time_minutes"
                            )

                        processed_article["article_metadata"]["enrichment"] = enrichment
                except Exception as exc:
                    self._emit_log(
                        "warning",
                        "collector.article.enrichment_failed",
                        source_id=source_id,
                        details={
                            "error": str(exc),
                            "url": raw_article.get("url"),
                        },
                    )
                    processed_article["article_metadata"]["enrichment"] = {
                        "language": processed_article.get("language", "en"),
                        "normalized_title": original_title[:500],
                        "normalized_summary": processed_article.get("summary", "")[
                            :2000
                        ],
                        "sentiment": "neutral",
                        "entities": [],
                        "topics": [],
                        "model_version": "fallback_v1",
                        "error": str(exc),
                    }

            try:
                article_model = CollectorArticleModel.model_validate(processed_article)

                # STAGE B: Quality Contract (Publishability Check)
                # Enforce STRICT length requirements for "pending" (publishable) status.
                # If short, it's saved as "enrichment_failed" (Candidate Only).
                # This ensures we discover everything (Stage A) but only publish quality (Stage B).
                min_publish_len = 500

                content_len = (
                    len(article_model.content.strip()) if article_model.content else 0
                )
                summary_len = (
                    len(article_model.summary.strip()) if article_model.summary else 0
                )

                if content_len < min_publish_len and summary_len < min_publish_len:
                    article_model.processing_status_override = "rejected"
                    article_model.article_metadata.source_metadata[
                        "stage_b_failure_reason"
                    ] = "content_too_short_for_publication"
                    self._emit_log(
                        "info",
                        "collector.contract.stage_b_failed",
                        source_id=source_id,
                        details={
                            "reason": "content_too_short_for_publication",
                            "len": max(content_len, summary_len),
                            "threshold": min_publish_len,
                            "url": str(article_model.url),
                        },
                    )

                return article_model
            except ValidationError as exc:
                print(f"DEBUG VALIDATION ERROR: {exc}", flush=True)
                self._emit_log(
                    "warning",
                    "collector.article.validation_failed",
                    source_id=source_id,
                    details={
                        "error": str(exc),
                        "url": raw_article.get("url", "unknown"),
                    },
                )
                self._send_to_dlq(
                    source_id,
                    raw_article.get("original_url", raw_article.get("url", "")),
                    "collector_payload_invalid",
                )
                return None

        except Exception as exc:
            self._emit_log(
                "error",
                "collector.article.process_exception",
                source_id=source_id,
                details={
                    "error": str(exc),
                    "title": raw_article.get("title"),
                    "url": raw_article.get("url"),
                },
            )
            return None

    def get_session_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de la sesión actual de recolección.

        Este método es como obtener un reporte de actividad de nuestro
        explorador después de una expedición completa.
        """
        current_time = datetime.now(timezone.utc)
        session_duration = current_time - self.session_stats["start_time"]
        articles_found = self.session_stats["articles_found"]
        articles_saved = self.session_stats["articles_saved"]

        return {
            **self.session_stats,
            "session_duration_minutes": session_duration.total_seconds() / 60,
            "articles_per_minute": articles_found
            / max(session_duration.total_seconds() / 60, 1),
            "success_rate": (articles_saved / max(articles_found, 1)) * 100,
            "end_time": current_time.isoformat(),
        }

    class _SessionStats(TypedDict):
        sources_checked: int
        articles_found: int
        articles_saved: int
        errors_encountered: int
        start_time: datetime
