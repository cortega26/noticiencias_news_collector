import asyncio
import contextlib
import hashlib
import json
import time

# Fixed imports
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from news_collector.collectors.base_collector import BaseCollector
from news_collector.config.settings import COLLECTION_CONFIG
from news_collector.utils.security import validate_url_safety

if TYPE_CHECKING:
    from news_collector.utils.logger import NewsCollectorLogger


class HtmlCollector(BaseCollector):
    """
    Colector genérico de HTML para fuentes sin RSS.

    Capacidades:
    - Extracción basada en selectores CSS configurables.
    - Soporte para metadatos (JSON-LD, OpenGraph).
    - Navegación optimizada con robots.txt compliance.
    """

    def __init__(
        self,
        logger_factory: Optional["NewsCollectorLogger"] = None,
        health_tracker: Optional[Any] = None,
    ) -> None:
        super().__init__(logger_factory=logger_factory, health_tracker=health_tracker)
        self.headers = {
            "User-Agent": COLLECTION_CONFIG["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Versión síncrona que delega en la implementación asíncrona mediante asyncio.run
        para simplificar el mantenimiento de una lógica única.
        """
        # Nota: Esto es un wrapper simple. En producción idealmente usamos el flujo async completo.
        return asyncio.run(self.collect_from_source_async(source_id, source_config))

    async def collect_from_source_async(  # noqa: C901
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        start_time = time.time()
        stats = {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": None,
            "processing_time": 0,
        }
        if self.health_tracker:
            self.health_tracker.record_attempt(source_id)

        url = source_config.get("url")
        if not url:
            stats["error_message"] = "URL no configurada"
            return stats

        job_key = self._make_job_key(source_id, url)
        if self._is_duplicate_job(job_key):
            stats["success"] = True
            return stats
        self._register_job(job_key)

        try:
            # 1. Robots & Safety
            allowed, robots_delay = self._respect_robots(url)
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                self._send_to_dlq(source_id, url, "robots_disallowed")
                return stats

            # SSRF check sync wrapper
            validate_url_safety(url)

            domain = urlparse(url).netloc
            self._enforce_domain_rate_limit(
                domain, robots_delay, source_config.get("min_delay_seconds")
            )

            # 2. Fetch HTML
            # 2. Fetch HTML (Conditional)
            html_content, status_code = await self._fetch_html_conditional(
                url, source_id, source_config
            )

            if status_code == 304:
                stats["success"] = True
                stats["articles_found"] = 0
                return stats

            if not html_content:
                stats["error_message"] = (
                    f"Error HTTP {status_code}"
                    if status_code
                    else "Error fetching content"
                )
                return stats

            # 3. Parse & Extract
            try:
                raw_articles = await asyncio.to_thread(
                    self._extract_articles_from_html,
                    html_content,
                    source_config,
                    source_id,
                )
            except Exception as e:
                stats["error_message"] = f"Error de parsing: {str(e)}"
                return stats

            if self.health_tracker:
                self.health_tracker.record_success(source_id, "fetch")
                self.health_tracker.record_success(
                    source_id, "parse", count=len(raw_articles)
                )

            stats["articles_found"] = len(raw_articles)

            # 4. Save
            processed_candidates = []
            for raw in raw_articles:
                # Rate limit between articles
                self._enforce_domain_rate_limit(
                    domain, robots_delay, source_config.get("min_delay_seconds")
                )

                # Fetch full content
                if raw.get("url"):
                    async with httpx.AsyncClient(
                        timeout=COLLECTION_CONFIG.get("request_timeout", 30)
                    ) as fetch_client:
                        full_text = await self._fetch_article_content(
                            fetch_client, raw["url"], source_config
                        )
                    if full_text:
                        raw["content"] = full_text

                # Basic validation hook
                processed = self._process_article_html(raw, source_config, source_id)
                if processed:
                    processed_candidates.append(processed)

            # Apply strict sequential filters and save
            saved_count = self._filter_and_save_articles(
                source_id, processed_candidates, limit=5
            )
            stats["articles_saved"] = saved_count
            stats["success"] = True

        except Exception as e:
            stats["error_message"] = f"Excepción inesperada: {str(e)}"
            self._emit_log(
                "error",
                "collector.html.exception",
                source_id=source_id,
                details={"error": str(e)},
            )
            if self.health_tracker:
                self.health_tracker.record_failure(
                    source_id, "collector.fetch", "exception", {"error": str(e)}
                )

        finally:
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)

        return stats

    def _extract_articles_from_html(  # noqa: C901
        self, html: str, config: Dict[str, Any], source_id: str
    ) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        articles = []

        # Strategy 1: JSON-LD (High Precision)
        ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in ld_scripts:
            try:
                script_payload = script.string
                if not script_payload:
                    continue
                data = json.loads(script_payload)
                if "@type" in data and data["@type"] in [
                    "ItemList",
                    "Blog",
                    "NewsMediaOrganization",
                ]:
                    items = data.get("itemListElement", []) or data.get("blogPost", [])
                    for item in items:
                        if isinstance(item, dict):
                            art = self._parse_json_ld_article(item)
                            if art:
                                articles.append(art)
            except Exception:  # noqa: S112
                continue

        if articles:
            return articles

        # Strategy 2: CSS Selectors (Configured)
        selectors = config.get("html_selectors", {})
        container_sel = selectors.get("container", "article")
        link_sel = selectors.get("link", "a")
        title_sel = selectors.get("title", "h2, h3")

        for container in soup.select(container_sel):
            try:
                # Link
                link_tag = (
                    container.select_one(link_sel) if link_sel != "self" else container
                )
                if not link_tag or not link_tag.has_attr("href"):
                    continue
                url = link_tag["href"]

                # Title
                title_tag = container.select_one(title_sel)
                title = title_tag.get_text(strip=True) if title_tag else ""
                if not title and link_tag:
                    title = link_tag.get_text(strip=True)

                if url and title:
                    articles.append(
                        {
                            "title": title,
                            "url": url,  # Needs normalization
                            "description": "",
                            "date": None,
                        }
                    )
            except Exception:  # noqa: S112
                continue

        return articles

    def _parse_json_ld_article(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Simplified parser
        return {
            "title": item.get("headline", "") or item.get("name", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
            "date": item.get("datePublished", ""),
        }

    def _process_article_html(
        self, raw: Dict[str, Any], config: Dict[str, Any], source_id: str
    ) -> Optional[Dict[str, Any]]:
        # Validate and structure
        if not raw.get("url") or not raw.get("title"):
            return None

        # Normalize URL
        base_url = config.get("url", "")
        article_url = raw["url"]
        if not article_url.startswith("http"):
            article_url = urljoin(base_url, article_url)

        summary = raw.get("description", "")
        content = raw.get("content", "")

        # Word count approximation
        # Ensure > 0 to pass validation (fallback to title)
        word_count = len((content or summary or raw["title"]).split())

        return {
            "title": raw["title"],
            "url": article_url,
            "summary": summary,
            "content": content,
            "published_date": raw.get("date") or datetime.now(timezone.utc),
            "source_id": source_id,
            "source_name": config.get("name", "Unknown Source"),
            "category": config.get("category", "unknown"),
            "source_metadata": {"type": "html"},
            "word_count": word_count,
            "reading_time_minutes": max(1, word_count // 200),
            "validation_flags": {
                "allow_short": True if word_count > 100 else False  # noqa: SIM210
            },
            "authors": [],
            "tags": [],
        }

    async def _fetch_article_content(
        self, client: httpx.AsyncClient, url: str, config: Dict[str, Any]
    ) -> Optional[str]:
        try:
            response = await client.get(url)
            if response.status_code >= 400:
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Configurable selectors
            selectors = config.get("html_selectors", {})
            article_sel = selectors.get("article_selector")

            container = None
            if article_sel:
                container = soup.select_one(article_sel)

            # Fallback heuristics
            if not container:
                container = (
                    soup.find("article")
                    or soup.find("main")
                    or soup.find("div", class_="content")
                    or soup.body
                )

            if not container:
                return None

            paragraphs = container.find_all("p")
            text = "\n\n".join(
                [
                    p.get_text(strip=True)
                    for p in paragraphs
                    if len(p.get_text(strip=True)) > 20
                ]
            )
            return text
        except Exception:
            return None

    async def _fetch_html_conditional(  # noqa: C901
        self, url: str, source_id: str, source_config: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Fetches HTML content using conditional GET (ETag/Last-Modified).
        Returns (content, status_code). Content is None if 304 or error.
        """
        cached_headers: Dict[str, Optional[str]] = {
            "etag": None,
            "last_modified": None,
            "content_hash": None,
        }
        with contextlib.suppress(Exception):
            cached_headers = (
                self.db_manager.get_source_feed_metadata(source_id) or cached_headers
            )

        headers = self.headers.copy()
        if cached_headers.get("etag"):
            headers["If-None-Match"] = cached_headers["etag"]
        if cached_headers.get("last_modified"):
            headers["If-Modified-Since"] = cached_headers["last_modified"]

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers=headers,
                timeout=COLLECTION_CONFIG.get("request_timeout", 30),
            ) as client:

                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = await client.get(url)

                        if response.status_code == 304:
                            self._emit_log(
                                "info",
                                "collector.html.not_modified",
                                source_id=source_id,
                            )
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                etag=response.headers.get("ETag")
                                or cached_headers.get("etag"),
                                last_modified=response.headers.get("Last-Modified")
                                or cached_headers.get("last_modified"),
                                content_hash=cached_headers.get("content_hash"),
                            )
                            return None, 304

                        if response.status_code >= 500:
                            # Server error, retry
                            if attempt < max_retries - 1:
                                await self._backoff_sleep_async(attempt)
                                continue
                            return None, response.status_code

                        if response.status_code == 429:
                            # 429 Too Many Requests - Respect Retry-After
                            retry_at = self._parse_retry_after(response)
                            if not retry_at:
                                # Default to 15 minutes if no header provided
                                retry_at = datetime.now(timezone.utc) + timedelta(
                                    minutes=15
                                )

                            self._emit_log(
                                "warning",
                                "collector.rate_limit.exceeded",
                                source_id=source_id,
                                details={
                                    "retry_after": retry_at.isoformat(),
                                    "header": response.headers.get("Retry-After"),
                                },
                            )

                            # Force Circuit Breaker COOLDOWN
                            self.db_manager.update_source_circuit_state(
                                source_id,
                                success=False,
                                error_message="HTTP 429: Rate Limit Exceeded",
                                force_cooldown_until=retry_at,
                            )
                            return None, 429

                        if response.status_code >= 400:
                            # Client error (403, 404), strictly no retry
                            return None, response.status_code

                        # Success 200
                        content = response.text
                        content_hash = hashlib.sha256(response.content).hexdigest()

                        if cached_headers.get("content_hash") == content_hash:
                            self._emit_log(
                                "info",
                                "collector.html.content_unchanged",
                                source_id=source_id,
                            )
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                                content_hash=content_hash,
                            )
                            return None, 304

                        self.db_manager.update_source_feed_metadata(
                            source_id,
                            etag=response.headers.get("ETag"),
                            last_modified=response.headers.get("Last-Modified"),
                            content_hash=content_hash,
                        )

                        return content, response.status_code

                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt < max_retries - 1:
                            await self._backoff_sleep_async(attempt)
                            continue
                        return None, None

        except Exception as e:
            self._emit_log(
                "error",
                "collector.fetch.exception",
                source_id=source_id,
                details={"error": str(e)},
            )
            return None, None
        return None, None
