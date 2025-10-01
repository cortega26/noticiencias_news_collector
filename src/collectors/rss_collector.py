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

import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import logging
import random
import urllib.robotparser as robotparser
import httpx

import requests
import feedparser

from src.utils.pydantic_compat import get_pydantic_module

ValidationError = get_pydantic_module().ValidationError

from .base_collector import BaseCollector
from .rate_limit_utils import calculate_effective_delay
from ..storage.database import get_database_manager
from config.settings import (
    COLLECTION_CONFIG,
    RATE_LIMITING_CONFIG,
    TEXT_PROCESSING_CONFIG,
    ROBOTS_CONFIG,
)
from src.utils.url_canonicalizer import canonicalize_url
from src.enrichment import enrichment_pipeline
from src.contracts import CollectorArticleModel

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """
    Colector especializado en feeds RSS y Atom.

    Esta clase es como un bibliotecario especializado que conoce íntimamente
    el lenguaje de los feeds RSS, sabe cómo extraer la información más valiosa
    de cada uno, y puede adaptarse a las particularidades de diferentes fuentes.

    Hereda de BaseCollector para mantener consistencia con otros tipos de
    colectores que podríamos agregar en el futuro (APIs, web scraping, etc.).
    """

    def __init__(self):
        super().__init__()
        self.db_manager = get_database_manager()
        self.session = self._create_session()

        # Estadísticas de la sesión actual
        self.session_stats = {
            "sources_checked": 0,
            "articles_found": 0,
            "articles_saved": 0,
            "errors_encountered": 0,
            "start_time": datetime.now(timezone.utc),
        }
        # Per-domain rate limiting state
        self._domain_last_request: Dict[str, float] = {}
        # Robots cache per domain (timestamp, parser)
        self._robots_cache: Dict[str, Tuple[float, robotparser.RobotFileParser]] = {}

    def _create_session(self) -> requests.Session:
        """
        Crea una sesión HTTP optimizada para recolección de feeds.

        Una sesión HTTP es como tener un navegador persistente que recuerda
        cookies, mantiene conexiones abiertas, y puede aplicar configuraciones
        consistentes a todas las requests. Esto es mucho más eficiente que
        crear una nueva conexión para cada feed.
        """
        session = requests.Session()

        # Headers que nos identifican como un bot legítimo y responsable
        session.headers.update(
            {
                "User-Agent": COLLECTION_CONFIG["user_agent"],
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

    # Robots/TOS helpers
    def _get_robots(self, domain: str) -> Optional[robotparser.RobotFileParser]:
        if not ROBOTS_CONFIG["respect_robots"]:
            return None
        now = time.time()
        ttl = ROBOTS_CONFIG["cache_ttl_seconds"]
        cached = self._robots_cache.get(domain)
        if cached and (now - cached[0] < ttl):
            return cached[1]
        try:
            robots_url = f"https://{domain}/robots.txt"
            resp = httpx.get(
                robots_url,
                timeout=5.0,
                headers={"User-Agent": COLLECTION_CONFIG["user_agent"]},
            )
            if resp.status_code >= 400:
                return None
            rp = robotparser.RobotFileParser()
            rp.parse(resp.text.splitlines())
            self._robots_cache[domain] = (now, rp)
            return rp
        except Exception:
            return None

    def _respect_robots(self, url: str) -> Tuple[bool, Optional[float]]:
        if not ROBOTS_CONFIG["respect_robots"]:
            return (True, None)
        domain = urlparse(url).netloc
        rp = self._get_robots(domain)
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

    # Per-domain rate limiting with robots.txt crawl-delay
    def _enforce_domain_rate_limit(
        self,
        domain: str,
        robots_delay: Optional[float] = None,
        source_min_delay: Optional[float] = None,
    ):
        now = time.time()
        last = self._domain_last_request.get(domain, 0.0)
        effective_delay = calculate_effective_delay(
            domain, robots_delay, source_min_delay
        )
        jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))
        wait = (last + effective_delay + jitter) - now
        if wait > 0:
            time.sleep(wait)
        self._domain_last_request[domain] = time.time()

    def _backoff_sleep(self, attempt: int):
        base = RATE_LIMITING_CONFIG.get("backoff_base", 0.5)
        max_b = RATE_LIMITING_CONFIG.get("backoff_max", 10.0)
        jitter = random.uniform(0, RATE_LIMITING_CONFIG.get("jitter_max", 0.3))
        delay = min(max_b, (base * (2**attempt)) + jitter)
        time.sleep(delay)

    def collect_from_source(
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
            # Idempotent job key per source feed
            job_key = self._make_job_key(source_id, source_config["url"])
            if self._is_duplicate_job(job_key):
                logger.info(
                    f"🟡 Trabajo duplicado detectado para {source_id}, omitiendo"
                )
                stats["success"] = True
                return stats
            self._register_job(job_key)
            logger.info(
                f"🔍 Iniciando recolección de {source_config['name']} ({source_id})"
            )

            # Respetar robots.txt y rate limiting por dominio
            allowed, robots_delay = self._respect_robots(source_config["url"])
            if not allowed:
                stats["error_message"] = "Bloqueado por robots.txt"
                self._send_to_dlq(source_id, source_config["url"], "robots_disallowed")
                return stats
            domain = urlparse(source_config["url"]).netloc
            self._enforce_domain_rate_limit(
                domain, robots_delay, source_config.get("min_delay_seconds")
            )

            # Obtener el feed RSS
            feed_content, status_code = self._fetch_feed(
                source_id, source_config["url"]
            )
            if status_code == 304:
                logger.info(
                    "📭 Feed sin cambios para %s (HTTP 304 If-Modified-Since/ETag)",
                    source_id,
                )
                stats["success"] = True
                return stats

            if not feed_content:
                stats["error_message"] = "No se pudo obtener el feed"
                return stats

            # Parsear el feed con feedparser
            parsed_feed = feedparser.parse(feed_content)

            # Verificar que el feed sea válido
            if parsed_feed.bozo and not self._is_acceptable_bozo(parsed_feed):
                stats["error_message"] = (
                    f"Feed malformado: {parsed_feed.bozo_exception}"
                )
                logger.warning(
                    f"⚠️  Feed malformado en {source_id}: {parsed_feed.bozo_exception}"
                )
                return stats

            # Extraer artículos del feed
            raw_articles = self._extract_articles_from_feed(parsed_feed, source_config)
            stats["articles_found"] = len(raw_articles)

            if not raw_articles:
                logger.info(f"📭 No se encontraron artículos nuevos en {source_id}")
                stats["success"] = True
                return stats

            # Procesar y guardar cada artículo
            saved_count = 0
            for raw_article in raw_articles:
                try:
                    processed_article = self._process_article(
                        raw_article, source_id, source_config
                    )
                    if processed_article and self._save_article(processed_article):
                        saved_count += 1

                except Exception as e:
                    logger.error(f"Error procesando artículo individual: {e}")
                    self.session_stats["errors_encountered"] += 1

            stats["articles_saved"] = saved_count
            stats["success"] = True

            logger.info(
                f"✅ {source_id}: {saved_count}/{len(raw_articles)} artículos guardados"
            )

        except requests.RequestException as e:
            stats["error_message"] = f"Error de red: {str(e)}"
            logger.error(f"❌ Error de red en {source_id}: {e}")

        except Exception as e:
            stats["error_message"] = f"Error inesperado: {str(e)}"
            logger.error(f"❌ Error inesperado en {source_id}: {e}")

        finally:
            stats["processing_time"] = time.time() - start_time
            self._update_source_stats(source_id, stats)
            self.session_stats["sources_checked"] += 1
            self.session_stats["articles_found"] += stats["articles_found"]
            self.session_stats["articles_saved"] += stats["articles_saved"]

        return stats

    def _fetch_feed(
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
            }
            try:
                cached_headers = self.db_manager.get_source_feed_metadata(source_id)
            except Exception as metadata_error:
                logger.warning(
                    "No se pudo obtener metadata HTTP previa para %s: %s",
                    source_id,
                    metadata_error,
                )
            for attempt in range(0, max_retries + 1):
                try:
                    conditional_headers = {}
                    if cached_headers.get("etag"):
                        conditional_headers["If-None-Match"] = cached_headers["etag"]
                    if cached_headers.get("last_modified"):
                        conditional_headers["If-Modified-Since"] = cached_headers[
                            "last_modified"
                        ]

                    response = self.session.get(
                        feed_url,
                        timeout=COLLECTION_CONFIG["request_timeout"],
                        headers=conditional_headers or None,
                    )
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < max_retries:
                            self._backoff_sleep(attempt)
                            continue
                        else:
                            logger.warning(
                                f"HTTP {response.status_code} agotó reintentos para {feed_url}"
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
                                logger.warning(
                                    "No se pudo actualizar metadata HTTP para %s tras 304: %s",
                                    source_id,
                                    update_error,
                                )
                        return (None, 304)
                    response.raise_for_status()
                    # Verificar que el contenido sea XML válido
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(
                        xml_type in content_type for xml_type in ["xml", "rss", "atom"]
                    ):
                        logger.warning(
                            f"⚠️  Content-Type sospechoso: {content_type} para {feed_url}"
                        )
                    # Verificar tamaño razonable (protección contra feeds gigantes)
                    content_length = len(response.content)
                    if content_length > 10 * 1024 * 1024:  # 10MB límite
                        logger.warning(
                            f"⚠️  Feed muy grande ({content_length} bytes): {feed_url}"
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
                            logger.warning(
                                "No se pudo actualizar metadata HTTP para %s: %s",
                                source_id,
                                update_error,
                            )

                    return (response.text, response.status_code)
                except (
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                ) as re:
                    if attempt < max_retries:
                        self._backoff_sleep(attempt)
                        continue
                    else:
                        logger.warning(
                            f"⏰ Timeout/ConnError tras reintentos: {feed_url} | {re}"
                        )
                        return (None, None)
                except requests.exceptions.TooManyRedirects:
                    logger.warning(f"🔄 Demasiados redirects: {feed_url}")
                    return (None, None)
            return (None, None)
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error obteniendo feed {feed_url}: {e}")
            return (None, None)

    def _is_acceptable_bozo(self, parsed_feed) -> bool:
        """
        Determina si un feed "bozo" (malformado) es aceptable para procesar.

        feedparser marca muchos feeds como "bozo" por pequeñas imperfecciones
        que no impiden extraer información útil. Este método es como tener
        un experto que puede distinguir entre errores menores y problemas graves.
        """
        if not parsed_feed.bozo:
            return True

        # Excepciones que podemos tolerar
        acceptable_exceptions = [
            "InvalidDocument",  # Documentos con pequeños errores de formato
            "UndeclaredNamespace",  # Namespaces no declarados pero manejables
        ]

        exception_name = parsed_feed.bozo_exception.__class__.__name__
        return exception_name in acceptable_exceptions

    def _extract_articles_from_feed(
        self, parsed_feed, source_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extrae artículos individuales de un feed parseado.

        Este método es como tener un bibliotecario experto que puede leer
        diferentes estilos de catálogos (RSS, Atom, diferentes versiones)
        y extraer la información esencial de cada libro de manera consistente.
        """
        articles = []
        max_articles = COLLECTION_CONFIG["max_articles_per_source"]
        recent_threshold = datetime.now(timezone.utc) - timedelta(
            days=COLLECTION_CONFIG["recent_days_threshold"]
        )

        # Procesar entradas del feed
        for entry in parsed_feed.entries[:max_articles]:
            try:
                # Extraer fecha de publicación
                pub_dt, pub_off_min, pub_tz_name = self._extract_publication_timestamp(
                    entry
                )

                # Filtrar artículos muy antiguos (opcional, según configuración)
                if pub_dt and pub_dt < recent_threshold:
                    continue

                # Extraer información básica
                original_url = entry.get("link", "")
                canonical_url = canonicalize_url(original_url)

                article_data = {
                    "title": self._clean_text(entry.get("title", "Sin título")),
                    "url": canonical_url,
                    "summary": self._extract_summary(entry),
                    "published_date": pub_dt,
                    "published_tz_offset_minutes": pub_off_min,
                    "published_tz_name": pub_tz_name,
                    "authors": self._extract_authors(entry),
                    "category": source_config["category"],
                    "source_metadata": self._extract_source_metadata(
                        entry, parsed_feed
                    ),
                    "original_url": original_url,
                }

                # Validar que tengamos información mínima necesaria
                if self._validate_article_data(article_data):
                    articles.append(article_data)

            except Exception as e:
                logger.warning(f"Error extrayendo artículo individual: {e}")
                continue

        return articles

    def _extract_publication_timestamp(self, entry) -> Tuple[datetime, int, str]:
        """
        Extrae la fecha de publicación de manera robusta.

        Las fechas en RSS son notoriamente inconsistentes. Este método
        es como tener un traductor que entiende todos los dialectos posibles
        de cómo se puede expresar una fecha.
        """
        from src.utils.datetime_utils import parse_to_utc_with_tzinfo

        date_fields = ["published_parsed", "updated_parsed", "published", "updated"]
        for field in date_fields:
            if hasattr(entry, field):
                date_value = getattr(entry, field)
                if date_value:
                    try:
                        return parse_to_utc_with_tzinfo(date_value)
                    except Exception as e:
                        logger.debug(f"Error parseando fecha {date_value}: {e}")
                        continue
        # Fallback: now in UTC
        dt, off, name = parse_to_utc_with_tzinfo(None)
        return dt, off, name

    def _extract_summary(self, entry) -> str:
        """
        Extrae y limpia el resumen del artículo.

        Los feeds RSS pueden tener el contenido en varios campos y formatos.
        Este método es como tener un editor que sabe encontrar la esencia
        del artículo sin importar cómo esté formateado.
        """
        # Campos posibles para el contenido
        content_fields = ["summary", "description", "content"]

        for field in content_fields:
            if hasattr(entry, field):
                content = getattr(entry, field)

                # Manejar diferentes formatos de contenido
                if isinstance(content, list) and content:
                    content = (
                        content[0].get("value", "")
                        if isinstance(content[0], dict)
                        else str(content[0])
                    )
                elif isinstance(content, dict):
                    content = content.get("value", "")

                if content and isinstance(content, str):
                    # Limpiar HTML si existe
                    cleaned_content = self._clean_html(content)
                    if (
                        len(cleaned_content)
                        >= TEXT_PROCESSING_CONFIG["min_content_length"]
                    ):
                        return cleaned_content

        return ""

    def _clean_html(self, html_content: str) -> str:
        """
        Limpia contenido HTML para obtener texto plano.

        Muchos feeds incluyen HTML en sus descripciones. Este método
        es como tener un filtro inteligente que mantiene la información
        importante pero elimina por completo el formato innecesario.
        """
        if not html_content:
            return ""

        try:
            from src.utils.text_cleaner import clean_html as _clean

            return _clean(html_content)
        except Exception as e:
            logger.warning(f"Error limpiando HTML: {e}")
            import re

            text = re.sub("<[^<]+?>", "", html_content)
            return " ".join(text.split())

    def _extract_authors(self, entry) -> List[str]:
        """
        Extrae información de autores cuando está disponible.

        La información de autores en feeds RSS es muy inconsistente.
        Este método hace lo mejor posible para extraer esta información
        valiosa cuando está presente.
        """
        authors = []

        # Campos posibles para autores
        if hasattr(entry, "author") and entry.author:
            authors.append(self._clean_text(entry.author))

        if hasattr(entry, "authors") and entry.authors:
            for author in entry.authors:
                if isinstance(author, dict):
                    name = author.get("name") or author.get("email", "")
                else:
                    name = str(author)

                if name:
                    authors.append(self._clean_text(name))

        # Buscar autores en tags personalizados (para algunos journals)
        if hasattr(entry, "tags"):
            for tag in entry.tags:
                if "author" in tag.get("term", "").lower():
                    authors.append(self._clean_text(tag.get("term", "")))

        return list(set(authors))  # Remover duplicados

    def _extract_source_metadata(self, entry, parsed_feed) -> Dict[str, Any]:
        """
        Extrae metadatos específicos de la fuente.

        Diferentes fuentes incluyen información especializada en sus feeds.
        Este método es como tener un detective que puede encontrar pistas
        valiosas específicas de cada tipo de fuente.
        """
        metadata = {}

        # DOI (muy importante para papers académicos)
        doi = self._extract_doi(entry)
        if doi:
            metadata["doi"] = doi

        # Tags/categorías
        if hasattr(entry, "tags") and entry.tags:
            metadata["tags"] = [
                tag.get("term", "") for tag in entry.tags if tag.get("term")
            ]

        # Información del journal/revista
        if hasattr(parsed_feed, "feed"):
            feed_info = parsed_feed.feed
            if hasattr(feed_info, "title"):
                metadata["feed_title"] = feed_info.title

        # Enlaces adicionales
        if hasattr(entry, "links") and entry.links:
            metadata["additional_links"] = [
                {"href": link.get("href"), "type": link.get("type", "unknown")}
                for link in entry.links
                if link.get("href")
            ]

        # ID único del entry (útil para tracking)
        if hasattr(entry, "id") and entry.id:
            metadata["entry_id"] = entry.id

        return metadata

    def _extract_doi(self, entry) -> Optional[str]:
        """
        Extrae DOI (Digital Object Identifier) cuando está disponible.

        Los DOIs son cruciales para artículos académicos porque proporcionan
        un enlace permanente al paper original. Este método busca DOIs
        en varios lugares donde pueden aparecer en feeds académicos.
        """
        import re

        doi_pattern = r"10\.\d{4,}/[-._;()/:\w\[\]]+[^.\s]"

        # Buscar en diferentes campos
        search_fields = []

        if hasattr(entry, "id"):
            search_fields.append(entry.id)

        if hasattr(entry, "summary"):
            search_fields.append(entry.summary)

        if hasattr(entry, "links"):
            for link in entry.links:
                if link.get("href"):
                    search_fields.append(link["href"])

        # Buscar patrón DOI en todos los campos
        for field in search_fields:
            if field and isinstance(field, str):
                match = re.search(doi_pattern, field, re.IGNORECASE)
                if match:
                    return match.group()

        return None

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
            content_for_stats = (
                f"{processed_article['title']} {processed_article['summary']}"
            )
            processed_article["word_count"] = len(content_for_stats.split())
            processed_article["reading_time_minutes"] = max(
                1, processed_article["word_count"] // 200
            )

            # Detección simple de idioma (determinística)
            try:
                from src.utils.text_cleaner import detect_language_simple

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
            except Exception as exc:  # pragma: no cover - enrichment should not fail
                logger.warning(f"Enrichment failed: {exc}")

            try:
                return CollectorArticleModel.model_validate(processed_article)
            except ValidationError as exc:
                logger.warning(
                    "Payload validation failed for %s: %s",
                    raw_article.get("url", "unknown"),
                    exc,
                )
                self._send_to_dlq(
                    source_id,
                    raw_article.get("original_url", raw_article.get("url", "")),
                    "collector_payload_invalid",
                )
                return None

        except Exception as e:
            logger.error(
                f"Error procesando artículo {raw_article.get('title', 'sin título')}: {e}"
            )
            return None

    def _save_article(
        self, article_data: CollectorArticleModel | Dict[str, Any]
    ) -> bool:
        """
        Guarda un artículo procesado en la base de datos.

        Este método es como tener un archivista meticuloso que verifica
        que no tengamos duplicados antes de agregar cada nuevo documento
        a nuestra colección.
        """
        try:
            saved_article = self.db_manager.save_article(article_data)
            if saved_article:
                title = (
                    article_data.title
                    if isinstance(article_data, CollectorArticleModel)
                    else article_data["title"]
                )
                logger.debug(f"📚 Artículo guardado: {title[:50]}...")
                return True
            else:
                title = (
                    article_data.title
                    if isinstance(article_data, CollectorArticleModel)
                    else article_data["title"]
                )
                logger.debug(f"📋 Artículo duplicado omitido: {title[:50]}...")
                return False

        except ValueError as exc:
            title = (
                article_data.title
                if isinstance(article_data, CollectorArticleModel)
                else article_data.get("title", "sin título")
            )
            logger.error(f"Error de validación guardando artículo {title[:50]}: {exc}")
            return False
        except Exception as e:
            logger.error(f"Error guardando artículo: {e}")
            return False

    def _update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        """
        Actualiza las estadísticas de una fuente después de la recolección.

        Este método mantiene un registro detallado del performance de cada
        fuente, como mantener un expediente de cada proveedor de libros.
        """
        try:
            self.db_manager.update_source_stats(source_id, stats)
        except Exception as e:
            logger.error(f"Error actualizando estadísticas de fuente {source_id}: {e}")

    def _validate_article_data(self, article_data: Dict[str, Any]) -> bool:
        """
        Valida que un artículo tenga la información mínima necesaria.

        Este método es como un control de calidad que asegura que solo
        artículos con información suficiente pasen al siguiente paso.
        """
        # Verificaciones básicas
        if not article_data.get("title") or len(article_data["title"].strip()) < 10:
            return False

        if not article_data.get("url") or not article_data["url"].startswith("http"):
            return False

        # Verificar que el contenido no sea demasiado corto
        summary = article_data.get("summary", "")
        if len(summary) < TEXT_PROCESSING_CONFIG["min_content_length"]:
            return False

        # Verificar que no sea spam o clickbait obvio
        title_lower = article_data["title"].lower()
        penalty_keywords = TEXT_PROCESSING_CONFIG["penalty_keywords"]

        if any(keyword.lower() in title_lower for keyword in penalty_keywords):
            logger.debug(
                f"Artículo rechazado por keywords de penalización: {article_data['title']}"
            )
            return False

        return True

    def _clean_text(self, text: str) -> str:
        """
        Limpia y normaliza texto de manera consistente.

        Este método es como tener un editor que aplica reglas de estilo
        consistentes a cada texto que procesamos.
        """
        if not text:
            return ""

        from src.utils.text_cleaner import normalize_text

        return normalize_text(text)

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
