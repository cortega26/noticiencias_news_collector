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

from news_collector.config.settings import COLLECTION_CONFIG
from news_collector.contracts import CollectorArticleModel
from news_collector.enrichment import enrichment_pipeline
from news_collector.logic.parsers.image_extractor import ImageExtractor
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

        # Estadísticas de la sesión actual
        self.session_stats = {
            "sources_checked": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "errors_encountered": 0,
            "start_time": datetime.now(timezone.utc),
        }

    def _create_session(self):
        """Deprecated: Internal session is managed by RobustRequestsClient."""
        pass

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
                source_id, source_config["url"], source_config
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
        self, source_id: str, feed_url: str, source_config: Dict[str, Any] = None
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Obtiene el contenido de un feed RSS de manera robusta usando RobustRequestsClient.
        """
        try:
            cached_headers: Dict[str, Optional[str]] = {
                "etag": None,
                "last_modified": None,
                "content_hash": None,
            }
            try:  # noqa: SIM105
                cached_headers = (
                    self.db_manager.get_source_feed_metadata(source_id)
                    or cached_headers
                )
            except Exception:  # noqa: SIM105,S110
                # Log warning but continue
                pass

            # SSRF Check is done inside client, but we can double check or rely on client.
            # Client.get(ignore_ssrf=False) does it.

            request_headers = {}
            # ETag / Last-Modified Logic
            if cached_headers.get("etag"):
                request_headers["If-None-Match"] = cached_headers["etag"]
            if cached_headers.get("last_modified"):
                request_headers["If-Modified-Since"] = cached_headers["last_modified"]

            if source_config and source_config.get("headers"):
                request_headers.update(source_config["headers"])

            try:
                # Robust GET with retries enabled
                response = self.client.get(
                    feed_url,
                    headers=request_headers or None,
                    timeout=COLLECTION_CONFIG.get("request_timeout", 30),
                )
            except requests.RequestException as e:
                # Client raises execution for 403, 404, or exhausted retries
                status_code = getattr(e.response, "status_code", None)
                self._emit_log(
                    "warning",
                    "collector.feed.fetch_failed",
                    source_id=source_id,
                    details={"error": str(e), "url": feed_url, "status": status_code},
                )
                return (None, status_code)

            if response.status_code == 304:
                # Update metadata if headers changed (e.g. ETag rotation)
                try:  # noqa: SIM105
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        # content_hash is not available/changed since no content
                    )
                except Exception:  # noqa: S110
                    pass  # noqa: S110
                return (None, 304)

            # --- Validation & Metadata Update Logic (Preserved) ---
            # Verificar tamaño razonable
            content_length = len(response.content)
            if content_length > 10 * 1024 * 1024:  # 10MB límite
                self._emit_log(
                    "warning",
                    "collector.feed.too_large",
                    source_id=source_id,
                    details={"bytes": content_length},
                )
                return (None, response.status_code)

            # Validate Content-Type (Relaxed warning)
            content_type = response.headers.get("content-type", "").lower()
            if not any(
                x in content_type for x in ["xml", "rss", "atom", "json"]
            ):  # json feeds exist
                self._emit_log(
                    "debug",
                    "collector.feed.suspicious_content_type",
                    source_id=source_id,
                    details={"type": content_type},
                )

            response_text = response.text
            content_hash = hashlib.sha256(response.content).hexdigest()

            if cached_headers.get("content_hash") == content_hash:
                self._emit_log(
                    "info",
                    "collector.feed.content_unchanged",
                    source_id=source_id,
                    details={"hash": content_hash},
                )
                # Still update metadata execution time/headers if needed?
                # For now, just return 304 to signal skip.
                # But we might want to update the 'last_checked' timestamp in DB?
                # load_source_feed_metadata updates? No, update_source_feed_metadata does.
                # Let's update metadata before returning to ensure freshness?
                try:  # noqa: SIM105
                    self.db_manager.update_source_feed_metadata(
                        source_id,
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_hash=content_hash,
                    )
                except Exception:  # noqa: S110
                    pass  # noqa: S110
                return (None, 304)

            # Metadata Updates (Cleaned up)
            try:  # noqa: SIM105
                self.db_manager.update_source_feed_metadata(
                    source_id,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    content_hash=content_hash,
                )
            except Exception:  # noqa: S110
                pass  # noqa: S110  # Non-critical

            return (response_text, response.status_code)

        except Exception as exc:
            self._emit_log(
                "error",
                "collector.feed.unexpected_error",
                source_id=source_id,
                details={"error": str(exc)},
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

        # 3. PHASE THREE: Deep Processing (Full Text & Image Extraction)
        articles = []

        # or rely on the ImageExtractor to fetch if provided a URL (but avoiding double fetch if possible).
        # Optimization: We'll fetch the content ONCE here, pass to both extractors.

        for cand in selected_candidates:
            try:
                # Determine Fetch Mode
                # 1. 'fetch_mode' explicit config (rss_only, html, headless)
                # 2. Fallback to 'content_mode' if fetch_mode missing (legacy config compat)
                fetch_mode = source_config.get("fetch_mode")
                if not fetch_mode:
                    fetch_mode = (
                        "rss_only"
                        if source_config.get("content_mode") == "summary_only"
                        else "html"
                    )

                cand["content_mode"] = source_config.get(
                    "content_mode", "full_text"
                )  # Propagate to model

                # Fetch logic
                html_content = ""
                if fetch_mode == "rss_only":
                    self._emit_log(
                        "debug",
                        "collector.article.skipping_fetch",
                        details={"url": cand["url"], "mode": "rss_only"},
                    )
                elif fetch_mode == "html":
                    try:
                        self._emit_log(
                            "info",
                            "collector.article.fetching_content",
                            details={"url": cand["url"]},
                        )
                        # Using RobustClient (fail-fast on 403)
                        resp = self.client.get(cand["url"], timeout=15)
                        html_content = resp.text
                    except requests.RequestException as fetch_err:
                        # 403s will end up here immediately.
                        self._emit_log(
                            "warning",
                            "collector.article.fetch_failed",
                            details={
                                "url": cand["url"],
                                "error": str(fetch_err),
                                "status": getattr(
                                    fetch_err.response, "status_code", None
                                ),
                            },
                        )
                        # Do not fail the article, just proceed with empty HTML (will fallback to summary)

                # Full Text Extraction
                if html_content:
                    # Simple text extraction
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(html_content, "html.parser")
                    for script in soup(
                        [
                            "script",
                            "style",
                            "nav",
                            "footer",
                            "header",
                            "aside",
                            "noscript",
                        ]
                    ):
                        script.decompose()
                    cand["content"] = soup.get_text(separator=" ", strip=True)
                else:
                    # Ensure we fallback to summary if no content is found or allowed
                    if not cand.get("content"):
                        cand["content"] = cand.get("summary", "")

                # Image Extraction Logic
                image_status = "MISSING_SOURCE"
                image_source = None

                # 1. Check if feed provided an image
                feed_image = cand.get("image_url")
                if feed_image:
                    # Validate it
                    if self.image_extractor.validate_image(
                        type("Candidate", (), {"url": feed_image})()
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
                    candidates = self.image_extractor.extract_candidates(
                        html_content, cand["url"]
                    )
                    for img_cand in candidates:
                        if self.image_extractor.validate_image(img_cand):
                            cand["image_url"] = img_cand.url
                            image_status = "IMAGE_OK"
                            image_source = img_cand.source
                            break

                    if image_status != "IMAGE_OK":
                        if candidates:
                            image_status = "IMAGE_VALIDATION_FAILED"  # Found candidates but none valid
                        else:
                            image_status = "IMAGE_MISSING_SOURCE"  # No candidates found

                elif not feed_image and not html_content:
                    image_status = "IMAGE_DOWNLOAD_FAILED"

                # Add status to metadata
                if "article_metadata" not in cand:
                    cand["article_metadata"] = {}
                # The 'article_metadata' structure in 'cand' here is actually a DICT,
                # but 'CollectorArticleModel' expects 'article_metadata' field which is an 'ArticleMetadataModel'.
                # Wait, 'cand' here is a dict coming from RssParser.
                # In '_process_article' (called LATER or inside loop?), it maps to the model.
                # Actually, strictly speaking, 'cand' is just a dict here.
                # We need to pass this info to '_process_article' or put it in 'cand' such that '_process_article' sees it.
                # RssParser puts 'source_metadata' in cand.

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
                    "image_status": raw_article.get("_image_status"),
                    "image_source": raw_article.get("_image_source"),
                },
                "content_mode": raw_article.get("content_mode", "full_text"),
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
