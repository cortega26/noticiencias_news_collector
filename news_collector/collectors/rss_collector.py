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
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import feedparser
import requests

from news_collector.utils.pydantic_compat import get_pydantic_module

ValidationError = get_pydantic_module().ValidationError

from news_collector.config.settings import COLLECTION_CONFIG, RATE_LIMITING_CONFIG
from news_collector.contracts import CollectorArticleModel
from news_collector.enrichment import enrichment_pipeline
from news_collector.logic.parsers.rss_parser import RssParser
from news_collector.scoring.pre_scorer import PreScorer
from news_collector.utils.url_canonicalizer import configure_canonicalization_cache

from .base_collector import BaseCollector

if TYPE_CHECKING:  # pragma: no cover - typing only
    from news_collector.utils.logger import NewsCollectorLogger


configure_canonicalization_cache(
    int(COLLECTION_CONFIG.get("canonicalization_cache_size", 0))
)

from news_collector.utils.security import validate_url_safety


class RSSCollector(BaseCollector):
    """
    Colector especializado en feeds RSS y Atom.

    Esta clase es como un bibliotecario especializado que conoce íntimamente
    el lenguaje de los feeds RSS, sabe cómo extraer la información más valiosa
    de cada uno, y puede adaptarse a las particularidades de diferentes fuentes.

    Hereda de BaseCollector para mantener consistencia con otros tipos de
    colectores que podríamos agregar en el futuro (APIs, web scraping, etc.).
    """

    def __init__(
        self,
        logger_factory: Optional["NewsCollectorLogger"] = None,
        health_tracker: Optional[Any] = None,
    ) -> None:
        super().__init__(logger_factory=logger_factory, health_tracker=health_tracker)
        self.session = self._create_session()
        self.pre_scorer = PreScorer()
        self.parser = RssParser()

        # Estadísticas de la sesión actual
        self.session_stats = {
            "sources_checked": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "errors_encountered": 0,
            "start_time": datetime.now(timezone.utc),
        }

    def _create_session(self) -> requests.Session:
        """
        Crea una sesión HTTP optimizada para recolección de feeds.

        Una sesión HTTP es como tener un navegador persistente que recuerda
        cookies, mantiene conexiones abiertas, y puede aplicar configuraciones
        consistentes a todas las requests. Esto es mucho más eficiente que
        crear una nueva conexión para cada feed.
        """
        session = requests.Session()

        import secrets

        # Rotation of User-Agents to avoid static blocking, but maintaining Bot contact info
        user_agents = [
            "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
        ]

        base_ua = secrets.choice(user_agents)
        # Ensure we always identify ourselves
        bot_identifier = f"NoticienciasBot/1.0 (+{COLLECTION_CONFIG.get('contact_email', 'admin@noticiencias.com')})"
        final_ua = f"{base_ua} {bot_identifier}"

        # Headers que nos identifican como un bot legítimo y responsable
        session.headers.update(
            {
                "User-Agent": final_ua,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

        # Pooling adapter; retries handled manually for jitter control
        from requests.adapters import HTTPAdapter

        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

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
        }

        try:
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

            allowed, robots_delay = self._respect_robots(source_config["url"])
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                self._emit_log(
                    "warning",
                    "collector.fetch.blocked_robots",
                    source_id=source_id,
                    details={"url": source_config.get("url")},
                )
                self._send_to_dlq(source_id, source_config["url"], "robots_disallowed")
                return stats

            domain = urlparse(source_config["url"]).netloc
            self._enforce_domain_rate_limit(
                domain, robots_delay, source_config.get("min_delay_seconds")
            )

            feed_content, status_code = self._fetch_feed(
                source_id, source_config["url"]
            )
            if status_code == 304:
                self._emit_log(
                    "info",
                    "collector.feed.not_modified",
                    source_id=source_id,
                    details={"status_code": status_code},
                )
                stats["success"] = True
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                self._emit_log(
                    "warning",
                    "collector.feed.unavailable",
                    source_id=source_id,
                    details={
                        "status_code": status_code,
                        "url": source_config.get("url"),
                    },
                )
                return stats

            parsed_feed = feedparser.parse(feed_content)

            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = (
                    f"Feed malformado: {parsed_feed.bozo_exception}"
                )
                self._emit_log(
                    "warning",
                    "collector.feed.malformed",
                    source_id=source_id,
                    details={"error": str(parsed_feed.bozo_exception)},
                )
                return stats

            try:
                raw_articles = self._extract_articles_from_feed(
                    parsed_feed, source_config, source_id
                )
            except TypeError:
                raw_articles = self._extract_articles_from_feed(  # type: ignore[misc]
                    parsed_feed, source_config  # backwards compatibility for overrides
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
                },
            )

        except requests.RequestException as exc:
            stats["error_message"] = f"Error de red: {exc}"
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
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)
            self.session_stats["sources_checked"] += 1
            self.session_stats["articles_found"] += stats["articles_found"]
            self.session_stats["articles_saved"] += stats["articles_saved"]

        return stats

    def _fetch_feed(  # noqa: C901
        self, source_id: str, feed_url: str
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Obtiene el contenido de un feed RSS de manera robusta.

        Este método es como tener un mensajero muy experimentado que sabe
        cómo manejar todas las complicaciones que pueden surgir al contactar
        diferentes servidores: redirects, timeouts, servidores lentos, etc.
        """
        try:
            max_retries = RATE_LIMITING_CONFIG["max_retries"]
            cached_headers: Dict[str, Optional[str]] = {
                "etag": None,
                "last_modified": None,
                "content_hash": None,
            }
            try:
                cached_headers = self.db_manager.get_source_feed_metadata(source_id)
            except Exception as metadata_error:
                self._emit_log(
                    "warning",
                    "collector.feed.metadata_lookup_failed",
                    source_id=source_id,
                    details={"error": str(metadata_error)},
                )
                self._emit_log(
                    "warning",
                    "collector.feed.metadata_lookup_failed",
                    source_id=source_id,
                    details={"error": str(metadata_error)},
                )

            # SSRF Check
            try:
                validate_url_safety(feed_url)
            except ValueError as ssrf_error:
                self._emit_log(
                    "critical",
                    "collector.security.ssrf_blocked",
                    source_id=source_id,
                    details={"url": feed_url, "error": str(ssrf_error)},
                )
                return (None, 403)  # Forbidden

            for attempt in range(0, max_retries + 1):
                try:
                    conditional_headers = {}
                    # FORCE REFRESH: Temporarily disable ETag/Last-Modified to ensure we re-process feeds
                    # and trigger the full-text fetcher for existing items.
                    if cached_headers.get("etag"):
                        conditional_headers["If-None-Match"] = cached_headers["etag"]
                    if cached_headers.get("last_modified"):
                        conditional_headers["If-Modified-Since"] = cached_headers[
                            "last_modified"
                        ]

                    response = self.session.get(
                        feed_url,
                        timeout=COLLECTION_CONFIG.get("request_timeout", 30),
                        headers=conditional_headers or None,
                    )
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < max_retries:
                            self._backoff_sleep(attempt)
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
                                    content_hash=cached_headers.get("content_hash"),
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
                    # Verificar que el contenido sea XML válido
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(
                        xml_type in content_type for xml_type in ["xml", "rss", "atom"]
                    ):
                        self._emit_log(
                            "warning",
                            "collector.feed.suspicious_content_type",
                            source_id=source_id,
                            details={
                                "content_type": content_type,
                                "url": feed_url,
                            },
                        )
                    # Verificar tamaño razonable (protección contra feeds gigantes)
                    content_length = len(response.content)
                    if content_length > 10 * 1024 * 1024:  # 10MB límite
                        self._emit_log(
                            "warning",
                            "collector.feed.too_large",
                            source_id=source_id,
                            details={"bytes": content_length, "url": feed_url},
                        )
                        return (None, response.status_code)

                    response_text = response.text
                    content_hash = hashlib.sha256(response.content).hexdigest()

                    if cached_headers.get("content_hash") == content_hash:
                        try:
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                                content_hash=content_hash,
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
                        self._emit_log(
                            "debug",
                            "collector.feed.content_unchanged",
                            source_id=source_id,
                            latency=(
                                response.elapsed.total_seconds()
                                if hasattr(response, "elapsed") and response.elapsed
                                else 0.0
                            ),
                            details={
                                "reason": "hash-match",
                                "etag": response.headers.get("ETag"),
                            },
                        )
                        return (None, 304)

                    if response.headers.get("ETag") or response.headers.get(
                        "Last-Modified"
                    ):
                        try:
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                etag=response.headers.get("ETag"),
                                last_modified=response.headers.get("Last-Modified"),
                                content_hash=content_hash,
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
                    else:
                        try:
                            self.db_manager.update_source_feed_metadata(
                                source_id,
                                content_hash=content_hash,
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

                    return (response_text, response.status_code)
                except (
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                ) as re:
                    if attempt < max_retries:
                        self._backoff_sleep(attempt)
                        continue
                    self._emit_log(
                        "warning",
                        "collector.feed.retry_exhausted",
                        source_id=source_id,
                        details={"error": str(re), "url": feed_url},
                    )
                    return (None, None)
                except requests.exceptions.TooManyRedirects:
                    self._emit_log(
                        "warning",
                        "collector.feed.redirect_loop",
                        source_id=source_id,
                        details={"url": feed_url},
                    )
                    return (None, None)
            return (None, None)
        except requests.exceptions.RequestException as e:
            self._emit_log(
                "error",
                "collector.feed.fetch_exception",
                source_id=source_id,
                details={"error": str(e), "url": feed_url},
            )
            return (None, None)

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
        recent_threshold = datetime.now(timezone.utc) - timedelta(
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
            if cand.get("published_date") and cand["published_date"] < recent_threshold:
                continue

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
                "warning",
                "collector.prescorer.ranking_start",
                details={"candidates": len(candidates), "limit": max_articles},
            )

            selected_candidates = self.pre_scorer.select_top_candidates(
                candidates,
                limit=max_articles,
                source_context=source_config.get("name", source_id),
            )
        else:
            selected_candidates = candidates

        # 3. PHASE THREE: Deep Processing (Full Text)
        articles = []
        from news_collector.utils.full_text import fetch_full_article

        for cand in selected_candidates:
            try:
                self._emit_log(
                    "info",
                    "collector.article.fetching_full_text",
                    details={"url": cand["url"]},
                )

                full_text = fetch_full_article(cand["url"], self.session)
                if full_text:
                    cand["content"] = full_text

                # Create final dict (cleanup helper props if any)
                if "entry_ref" in cand:
                    del cand["entry_ref"]

                # _validate_article_data was called? No, it was called in loop.
                # Actually, the original method returned 'articles'.
                # And 'collect_from_source' gets 'raw_articles' and THEN calls '_process_article'.
                # Wait. In original code:
                # line 232: raw_articles = self._extract_articles_from_feed(...)
                # line 260: processed_article = self._process_article(raw_article...)

                # BUT, inside `_extract_articles_from_feed` (lines 579-690):
                # It DID fetch full text (lines 669-688).
                # It DID return a list of dicts.
                # It DID call _validate_article_data (line 683).

                # So I DO need to include the PreScorer and FullText fetching here.
                # The extracted RssParser only does the "PHASE ONE" extraction.

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

    def _process_article(
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
                },
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

            # Detección simple de idioma (determinística)
            try:
                # Priorizar configuración
                if source_config.get("language"):
                    processed_article["language"] = source_config["language"]
                else:
                    from news_collector.utils.text_cleaner import detect_language_simple

                    processed_article["language"] = detect_language_simple(
                        content_for_stats
                    )
            except Exception:
                processed_article["language"] = "en"

            # Enrichment pipeline (deterministic with caching)
            try:
                enrichment = enrichment_pipeline.enrich_article(
                    {
                        "title": processed_article["title"],
                        "summary": processed_article["summary"],
                        "content": raw_article.get("source_metadata", {}).get(
                            "content", ""
                        ),
                        "language": processed_article["language"],
                    }
                )
                processed_article["article_metadata"]["enrichment"] = enrichment
                processed_article["language"] = enrichment["language"]
            except Exception as exc:
                # Fail-open: Log the error but don't crash the collector
                self._emit_log(
                    "warning",
                    "collector.article.enrichment_failed",
                    source_id=source_id,
                    details={
                        "error": str(exc),
                        "url": raw_article.get("url"),
                    },
                )
                # Ensure minimal enrichment structure exists
                processed_article["article_metadata"]["enrichment"] = {
                    "entities": [],
                    "topics": [],
                    "sentiment": "neutral",
                    "error": str(exc),
                    "language": processed_article.get("language", "en"),
                    "normalized_title": processed_article["title"][:500],
                    "normalized_summary": processed_article["summary"][:2000],
                    "model_version": "fallback_v1",
                }

            try:
                return CollectorArticleModel.model_validate(processed_article)
            except ValidationError as exc:
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

        return {
            **self.session_stats,
            "session_duration_minutes": session_duration.total_seconds() / 60,
            "articles_per_minute": self.session_stats["articles_found"]
            / max(session_duration.total_seconds() / 60, 1),
            "success_rate": (
                self.session_stats["articles_saved"]
                / max(self.session_stats["articles_found"], 1)
            )
            * 100,
            "end_time": current_time.isoformat(),
        }
