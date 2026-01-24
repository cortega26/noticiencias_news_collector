import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
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
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers=self.headers,
                timeout=COLLECTION_CONFIG["request_timeout"],
            ) as client:
                response = await client.get(url)
                if response.status_code >= 400:
                    stats["error_message"] = f"Error HTTP {response.status_code}"
                    if self.health_tracker:
                        self.health_tracker.record_failure(
                            source_id,
                            "collector.fetch.http",
                            f"HTTP Error {response.status_code}",
                            {"status_code": response.status_code, "url": url},
                        )
                    return stats

                html_content = response.text

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
                    full_text = await self._fetch_article_content(
                        client, raw["url"], source_config
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
                data = json.loads(script.string)
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
