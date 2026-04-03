"""Manual URL ingestion workflow for the Refinery UI and CLI."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from news_collector.config.sources import ALL_SOURCES, save_sources
from news_collector.contracts.adapters import adapt_article_to_export
from news_collector.contracts.collector import CollectorArticleModel
from news_collector.contracts.export import ExportArticleModel, ExportContractV2
from news_collector.enrichment.headless_enricher import HeadlessEnricher
from news_collector.enrichment.http_enricher import HttpEnricher
from news_collector.enrichment.scholarly import ScholarlyMetadataEnricher
from news_collector.storage.database import DatabaseManager
from news_collector.utils.logger import get_logger
from news_collector.utils.security import validate_url_safety
from news_collector.utils.url_canonicalizer import canonicalize_url

logger = get_logger().create_module_logger(__name__)

_FETCH_METHODS = ("scholarly", "http", "headless")
_HOST_PREFIXES = ("www.", "feeds.")
MANUAL_INGEST_MIN_WORDS = 80
_NARRATIVE_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚáéíóúÑñ'-]+\b", flags=re.UNICODE)
_BUNDLE_NOISE_MARKERS = (
    "sourcescontent",
    "sourcemappingurl",
    "webpack://",
    "__webpack_require__",
    "function(",
    "=>",
    "export ",
    "import ",
    "const ",
    "let ",
    "var ",
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _normalize_host(raw_host: str | None) -> str:
    host = (raw_host or "").strip().lower()
    changed = True
    while changed and host:
        changed = False
        for prefix in _HOST_PREFIXES:
            if host.startswith(prefix):
                host = host[len(prefix) :]
                changed = True
    return host


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _excerpt_from_text(value: str | None, *, max_length: int = 280) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    excerpt = text[:max_length].strip()
    if len(text) > max_length:
        excerpt = f"{excerpt.rstrip(' .,;:')}\u2026"
    return excerpt


def _json_ld_items(soup: BeautifulSoup) -> Iterable[dict[str, Any]]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload = script.string or script.get_text()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                yield item


def _split_authors(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r",| and |;", value)
    return [part.strip() for part in parts if part.strip()]


def _extract_html_metadata(raw_html: str | None, article_url: str) -> dict[str, Any]:  # noqa: C901
    if not raw_html:
        return {}

    soup = BeautifulSoup(raw_html, "html.parser")

    def meta_value(*selectors: tuple[str, str]) -> str | None:
        for attr, key in selectors:
            tag = soup.find("meta", attrs={attr: key})
            if tag and tag.get("content"):
                return _clean_text(tag.get("content"))
        return None

    metadata: dict[str, Any] = {}

    metadata["title"] = (
        meta_value(
            ("property", "og:title"),
            ("name", "twitter:title"),
            ("name", "title"),
            ("name", "citation_title"),
        )
        or _clean_text(soup.title.string if soup.title else None)
        or _clean_text(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)
    )

    summary = meta_value(
        ("property", "og:description"),
        ("name", "twitter:description"),
        ("name", "description"),
        ("name", "dc.description"),
    )
    if not summary:
        first_paragraph = soup.find("p")
        summary = _clean_text(first_paragraph.get_text(" ", strip=True) if first_paragraph else None)
    metadata["summary"] = summary

    authors = (
        meta_value(
            ("name", "author"),
            ("property", "article:author"),
            ("name", "dc.creator"),
            ("name", "parsely-author"),
        )
        or None
    )
    metadata["authors"] = _split_authors(authors)

    image_url = meta_value(
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("name", "parsely-image-url"),
    )
    metadata["image_url"] = urljoin(article_url, image_url) if image_url else None

    published_date = meta_value(
        ("property", "article:published_time"),
        ("name", "parsely-pub-date"),
        ("name", "pubdate"),
        ("name", "dc.date"),
        ("name", "citation_publication_date"),
    )
    metadata["published_date"] = _parse_datetime(published_date)

    metadata["doi"] = meta_value(("name", "citation_doi"), ("name", "dc.identifier"))
    metadata["journal"] = meta_value(
        ("name", "citation_journal_title"),
        ("property", "og:site_name"),
    )

    for item in _json_ld_items(soup):
        item_type = item.get("@type")
        if isinstance(item_type, list):
            item_types = {str(value).lower() for value in item_type}
        else:
            item_types = {str(item_type).lower()}
        if not item_types.intersection({"article", "newsarticle", "scholarlyarticle"}):
            continue

        metadata["title"] = metadata.get("title") or _clean_text(
            item.get("headline") or item.get("name")
        )
        metadata["summary"] = metadata.get("summary") or _clean_text(
            item.get("description")
        )
        if not metadata.get("authors"):
            authors_value = item.get("author")
            parsed_authors: list[str] = []
            if isinstance(authors_value, list):
                for author in authors_value:
                    if isinstance(author, dict):
                        parsed_authors.append(
                            _clean_text(author.get("name")) or ""
                        )
                    else:
                        parsed_authors.append(_clean_text(author) or "")
            elif isinstance(authors_value, dict):
                parsed_authors.append(_clean_text(authors_value.get("name")) or "")
            else:
                parsed_authors.extend(_split_authors(_clean_text(authors_value)))
            metadata["authors"] = [author for author in parsed_authors if author]
        metadata["image_url"] = metadata.get("image_url") or (
            urljoin(article_url, item.get("image"))
            if isinstance(item.get("image"), str)
            else None
        )
        metadata["published_date"] = metadata.get("published_date") or _parse_datetime(
            item.get("datePublished")
        )
        metadata["doi"] = metadata.get("doi") or _clean_text(
            item.get("identifier") if isinstance(item.get("identifier"), str) else None
        )
        publisher = item.get("publisher")
        if not metadata.get("journal") and isinstance(publisher, dict):
            metadata["journal"] = _clean_text(publisher.get("name"))
        break

    return metadata


def _extract_scholarly_metadata(result: Mapping[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    authors = []
    for author in metadata.get("author", []) or []:
        if isinstance(author, dict):
            name = " ".join(
                value
                for value in [
                    _clean_text(author.get("given")),
                    _clean_text(author.get("family")),
                ]
                if value
            )
            if name:
                authors.append(name)
    created = metadata.get("created", {}).get("date-parts", [[None]])[0]
    published_date = None
    if isinstance(created, list) and created and created[0]:
        try:
            year = int(created[0])
            month = int(created[1]) if len(created) > 1 and created[1] else 1
            day = int(created[2]) if len(created) > 2 and created[2] else 1
            published_date = datetime(year, month, day, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            published_date = None
    abstract = metadata.get("abstract")
    abstract_text = None
    if abstract:
        abstract_text = _clean_text(re.sub(r"<[^>]+>", "", str(abstract)))
    journal_list = metadata.get("container-title")
    journal = None
    if isinstance(journal_list, list) and journal_list:
        journal = _clean_text(journal_list[0])
    return {
        "title": _clean_text(result.get("title")),
        "summary": _excerpt_from_text(abstract_text),
        "authors": authors,
        "published_date": published_date,
        "doi": _clean_text(metadata.get("DOI")),
        "journal": journal,
    }


def _content_length(value: Any) -> int:
    text = _clean_text(value)
    return len(text) if text else 0


def _word_count(value: Any) -> int:
    text = _clean_text(value) or ""
    return len(_NARRATIVE_WORD_RE.findall(text))


def _looks_like_bundle_noise(value: str | None) -> bool:
    text = (_clean_text(value) or "")[:5000]
    if not text:
        return False
    lowered = text.casefold()
    marker_hits = sum(lowered.count(marker) for marker in _BUNDLE_NOISE_MARKERS)
    punctuation_hits = sum(lowered.count(char) for char in "{}[]();<>")
    alpha_count = sum(1 for char in lowered if char.isalpha()) or 1
    return marker_hits >= 3 and (punctuation_hits / alpha_count) >= 0.08


class ManualUrlIngestService:
    """Fetches a single article URL, persists it, and prepares a one-off export."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        *,
        export_dir: Path | None = None,
    ) -> None:
        self.db = db_manager
        self.http = HttpEnricher()
        self.headless = HeadlessEnricher()
        self.scholarly = ScholarlyMetadataEnricher()
        self.export_dir = export_dir or Path("temp/manual_ingest")

    def ingest(self, article_url: str) -> dict[str, Any]:
        canonical_url = canonicalize_url(str(article_url).strip()) or ""
        if not canonical_url:
            return {"status": "error", "message": "URL vacía o inválida."}

        try:
            validate_url_safety(canonical_url)
        except ValueError as exc:
            return {"status": "error", "message": f"URL bloqueada: {exc}"}

        parsed_url = urlparse(canonical_url)
        if not _normalize_host(parsed_url.hostname):
            return {"status": "error", "message": "URL inválida: host no reconocido."}

        existing_article = self.db.get_article_by_url(canonical_url)
        if existing_article is not None:
            export_model = adapt_article_to_export(existing_article)
            export_path = self._write_single_article_export(export_model)
            return self._build_result(
                export_model=export_model,
                export_path=export_path,
                source_created=False,
                article_exists=True,
                fetch_attempts=[
                    {
                        "method": "existing_record",
                        "success": True,
                        "reason": "already_saved",
                        "content_length": _content_length(existing_article.content),
                    }
                ],
            )

        source_id, source_config, source_created = self._resolve_or_create_source(
            canonical_url
        )
        fetch_attempts = self._run_fetches(canonical_url, source_config)
        payload, build_error = self._build_payload(
            canonical_url,
            source_id=source_id,
            source_config=source_config,
            source_created=source_created,
            fetch_attempts=fetch_attempts,
        )
        if payload is None:
            return {
                "status": "error",
                "message": (build_error or {}).get(
                    "message", "No se pudo construir un artículo válido desde la URL."
                ),
                "error_code": (build_error or {}).get("error_code", "source_unusable"),
                "source_id": source_id,
                "source_created": source_created,
                "fetch_attempts": self._public_attempts(fetch_attempts),
            }

        try:
            model = CollectorArticleModel.model_validate(payload)
        except Exception as exc:
            logger.warning("Manual URL payload validation failed for %s: %s", canonical_url, exc)
            return {
                "status": "error",
                "message": f"Payload inválido: {exc}",
                "source_id": source_id,
                "source_created": source_created,
                "fetch_attempts": self._public_attempts(fetch_attempts),
            }

        saved_article = self.db.save_article(model)
        if saved_article is None:
            existing_article = self.db.get_article_by_url(canonical_url)
            if existing_article is not None:
                export_model = adapt_article_to_export(existing_article)
                export_path = self._write_single_article_export(export_model)
                return self._build_result(
                    export_model=export_model,
                    export_path=export_path,
                    source_created=source_created,
                    article_exists=True,
                    fetch_attempts=self._public_attempts(fetch_attempts),
                )
            return {
                "status": "error",
                "message": "El artículo no pudo guardarse porque ya existe un duplicado equivalente.",
                "source_id": source_id,
                "source_created": source_created,
                "fetch_attempts": self._public_attempts(fetch_attempts),
            }

        export_model = adapt_article_to_export(saved_article)
        export_path = self._write_single_article_export(export_model)
        return self._build_result(
            export_model=export_model,
            export_path=export_path,
            source_created=source_created,
            article_exists=False,
            fetch_attempts=self._public_attempts(fetch_attempts),
        )

    def _resolve_or_create_source(
        self, canonical_url: str
    ) -> tuple[str, dict[str, Any], bool]:
        parsed = urlparse(canonical_url)
        normalized_host = _normalize_host(parsed.hostname)
        for source_id, source_cfg in ALL_SOURCES.items():
            source_host = _normalize_host(urlparse(str(source_cfg.get("url", ""))).hostname)
            if source_host and source_host == normalized_host:
                return source_id, dict(source_cfg), False

        source_id = f"manual_{normalized_host.replace('.', '_')}"
        existing = ALL_SOURCES.get(source_id)
        if existing:
            return source_id, dict(existing), False

        base_url = f"{parsed.scheme or 'https'}://{normalized_host}/"
        source_cfg = {
            "name": normalized_host,
            "url": base_url,
            "credibility_score": 0.5,
            "update_frequency": "manual",
            "category": "multidisciplinary",
            "language": "en",
            "description": f"Manual URL ingestion source for {normalized_host}",
            "typical_delay": 0,
            "content_mode": "full_text",
            "enrichment_strategy": "http",
            "headless_enabled": True,
            "headless_max_seconds": 60,
            "_group": "COMMUNITY_FEEDS",
            "tier": "D",
            "fetchability_score": 50,
            "crawl_interval_seconds": 86400,
            "manual_only": True,
            "etag": None,
            "last_modified": None,
        }

        updated_sources = dict(ALL_SOURCES)
        updated_sources[source_id] = source_cfg
        save_sources(updated_sources)
        self.db.initialize_sources({source_id: source_cfg})
        logger.info("Created manual-only source %s for host %s", source_id, normalized_host)
        return source_id, source_cfg, True

    def _run_fetches(
        self, canonical_url: str, source_config: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        attempts: list[dict[str, Any]] = []
        preferred_method = self._preferred_method(source_config)
        ordered_methods = []
        for method in (preferred_method, *_FETCH_METHODS):
            if method and method not in ordered_methods:
                ordered_methods.append(method)

        for method in ordered_methods:
            if method == "http":
                result = self.http.enrich(canonical_url)
                html_metadata = _extract_html_metadata(
                    result.get("raw_content"), canonical_url
                )
            elif method == "headless":
                result = self.headless.enrich(canonical_url, dict(source_config))
                html_metadata = _extract_html_metadata(
                    result.get("raw_content"), canonical_url
                )
            else:
                result = self.scholarly.enrich_url(canonical_url)
                html_metadata = _extract_scholarly_metadata(result)

            attempts.append(
                {
                    "method": method,
                    "success": bool(result.get("success")),
                    "reason": _clean_text(
                        result.get("reason")
                        or result.get("error")
                        or ("ok" if result.get("success") else "failed")
                    ),
                    "content": _clean_text(result.get("content")),
                    "content_length": _content_length(result.get("content")),
                    "metadata": html_metadata,
                }
            )

        return attempts

    def _build_payload(  # noqa: C901
        self,
        canonical_url: str,
        *,
        source_id: str,
        source_config: Mapping[str, Any],
        source_created: bool,
        fetch_attempts: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        best_content = None
        best_content_length = -1
        merged: dict[str, Any] = {
            "title": None,
            "summary": None,
            "authors": [],
            "published_date": None,
            "doi": None,
            "journal": None,
            "image_url": None,
        }

        for attempt in fetch_attempts:
            content = attempt.get("content")
            content_length = attempt.get("content_length", 0)
            if content and content_length > best_content_length:
                best_content = content
                best_content_length = content_length

            metadata = attempt.get("metadata")
            if not isinstance(metadata, dict):
                continue
            for key in ("title", "summary", "published_date", "doi", "journal", "image_url"):
                if merged.get(key) in (None, "", []):
                    merged[key] = metadata.get(key)
            if not merged["authors"] and metadata.get("authors"):
                merged["authors"] = list(metadata.get("authors") or [])

        inferred_published_date = False
        if not merged["published_date"]:
            merged["published_date"] = datetime.now(timezone.utc)
            inferred_published_date = True

        if not merged["summary"] and best_content:
            merged["summary"] = _excerpt_from_text(best_content)

        if not merged["title"]:
            parsed = urlparse(canonical_url)
            tail = parsed.path.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")
            inferred_title = _clean_text(tail.title())
            if inferred_title and len(inferred_title) >= 10:
                merged["title"] = inferred_title

        summary = _clean_text(merged["summary"])
        content = _clean_text(best_content)
        if not content and not summary:
            return None, {
                "error_code": "source_unusable",
                "message": "La URL no produjo contenido legible para redactar un artículo.",
            }

        if _looks_like_bundle_noise(content):
            return None, {
                "error_code": "source_unusable",
                "message": "La extracción devolvió ruido técnico o código fuente en lugar de texto periodístico legible.",
            }

        word_basis = content or summary or ""
        word_count = max(1, _word_count(word_basis))
        minimum_words = 40 if not content and summary else MANUAL_INGEST_MIN_WORDS
        if word_count < minimum_words:
            return None, {
                "error_code": "source_unusable",
                "message": (
                    "La URL no aportó suficiente texto narrativo para un artículo fiable "
                    f"({word_count} < {minimum_words} palabras)."
                ),
            }

        reading_time_minutes = max(1, word_count // 200 or 1)

        source_metadata = {
            "manual_ingest": {
                "canonical_url": canonical_url,
                "source_created": source_created,
                "resolved_source_id": source_id,
                "preferred_method": self._preferred_method(source_config),
                "fetch_attempts": self._public_attempts(fetch_attempts),
                "published_date_inferred": inferred_published_date,
            }
        }

        payload = {
            "url": canonical_url,
            "original_url": canonical_url,
            "title": merged["title"],
            "summary": summary or "",
            "content": content,
            "source_id": source_id,
            "source_name": source_config.get("name") or source_id,
            "category": source_config.get("category") or "multidisciplinary",
            "published_date": merged["published_date"],
            "authors": merged["authors"] or [],
            "language": "en",
            "doi": merged["doi"],
            "journal": merged["journal"],
            "is_preprint": False,
            "word_count": word_count,
            "reading_time_minutes": reading_time_minutes,
            "content_mode": "full_text" if content else "summary_only",
            "article_metadata": {
                "source_metadata": source_metadata,
                "original_url": canonical_url,
                "image_url": merged["image_url"],
                "processing_timestamp": datetime.now(timezone.utc),
            },
        }
        return payload, None

    def _preferred_method(self, source_config: Mapping[str, Any]) -> str:
        strategy = str(source_config.get("enrichment_strategy", "http")).strip().lower()
        if strategy == "scholarly":
            return "scholarly"
        if strategy == "headless_fallback":
            return "http"
        return "http"

    def _write_single_article_export(self, export_model: ExportArticleModel) -> Path:
        contract = ExportContractV2(
            generated_at=datetime.now(timezone.utc).isoformat(),
            article_count=1,
            articles=[export_model],
        )
        payload = contract.model_dump()
        payload["exported_at"] = datetime.now(timezone.utc).isoformat()

        self.export_dir.mkdir(parents=True, exist_ok=True)
        export_path = self.export_dir / f"manual_article_{export_model.id}.json"
        export_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return export_path

    def _build_result(
        self,
        *,
        export_model: ExportArticleModel,
        export_path: Path,
        source_created: bool,
        article_exists: bool,
        fetch_attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        export_article = export_model.model_dump()
        publication_meta = (
            export_model.metadata.get("publication", {})
            if isinstance(export_model.metadata, dict)
            else {}
        )
        publication_state = str(publication_meta.get("state") or "").strip()
        published_candidate = bool(export_model.published_at or export_model.published_url)
        publish_ready = bool(
            isinstance(publication_meta.get("frontend_checks"), dict)
            and publication_meta["frontend_checks"].get("ready_for_merge") is True
        )
        return {
            "status": "success",
            "article_id": export_model.id,
            "source_id": export_model.source_id,
            "source_created": source_created,
            "article_exists": article_exists,
            "published": publication_state in {"LIVE", "DEPLOYED", "MERGED"},
            "published_candidate": published_candidate,
            "publish_ready": publish_ready,
            "publication_state": publication_state or ("PR_CREATED" if published_candidate else "UNPUBLISHED"),
            "export_path": str(export_path),
            "fetch_attempts": fetch_attempts,
            "article": export_article,
        }

    def _public_attempts(
        self, fetch_attempts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        public_attempts = []
        for attempt in fetch_attempts:
            public_attempts.append(
                {
                    "method": attempt.get("method"),
                    "success": bool(attempt.get("success")),
                    "reason": attempt.get("reason"),
                    "content_length": int(attempt.get("content_length", 0)),
                }
            )
        return public_attempts
