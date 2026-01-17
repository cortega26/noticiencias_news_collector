# src/collectors/base_collector.py
# Clase base para todos los colectores del sistema
# ===============================================

"""
Esta clase base define la interfaz común que deben implementar todos los
colectores de nuestro sistema. Es como crear el plano arquitectónico que
seguirán todos nuestros "exploradores digitales", sin importar si van a
buscar información en RSS feeds, APIs, o cualquier otra fuente.

La filosofía aquí es crear un contrato claro que garantice que todos los
colectores se comporten de manera predecible y consistente, facilitando
el mantenimiento y la extensión del sistema.
"""

import hashlib
import json
import random
import time
import urllib.robotparser as robotparser
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import asyncio
import httpx

from news_collector.contracts import CollectorArticleModel
from news_collector.config.settings import (
    COLLECTION_CONFIG,
    DLQ_DIR,
    RATE_LIMITING_CONFIG,
    ROBOTS_CONFIG,
    TEXT_PROCESSING_CONFIG,
)
from news_collector.collectors.rate_limit_utils import calculate_effective_delay
from news_collector.storage.database import get_database_manager
from news_collector.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from news_collector.utils.logger import NewsCollectorLogger


class BaseCollector(ABC):
    """
    Clase base abstracta para todos los colectores del sistema.

    Esta clase es como el ADN común que comparten todos nuestros colectores:
    define qué características esenciales debe tener cada uno, pero permite
    que cada implementación específica (RSS, API, etc.) tenga su propia
    personalidad y especialización.

    Usando el patrón Template Method, proporcionamos una estructura común
    mientras permitimos customización específica por tipo de colector.
    """

    def __init__(self, logger_factory: Optional["NewsCollectorLogger"] = None) -> None:
        """Inicialización común para todos los colectores."""

        self.collector_type = self.__class__.__name__
        self.start_time: Optional[datetime] = None
        self.stats = {
            "total_sources_processed": 0,
            "total_articles_found": 0,
            "total_articles_saved": 0,
            "total_errors": 0,
            "processing_time_seconds": 0,
        }

        self.logger_factory: "NewsCollectorLogger" = logger_factory or get_logger()
        self.module_logger = self.logger_factory.create_module_logger(
            f"collectors.{self.collector_type.lower()}"
        )
        self._active_trace_id: Optional[str] = None
        self._active_session_id: Optional[str] = None

        self._emit_log(
            "info",
            "collector.instance.initialized",
            details={"collector_type": self.collector_type},
        )

        # Idempotency tracking for this run
        self._job_keys_seen: set[str] = set()

        # Per-domain rate limiting state
        self._domain_last_request: Dict[str, float] = {}
        # Robots cache per domain (timestamp, parser)
        self._robots_cache: Dict[str, Tuple[float, robotparser.RobotFileParser]] = {}
        
        self.db_manager = get_database_manager()

    @abstractmethod
    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Método abstracto que debe implementar cada colector específico.
        """
        pass

    async def collect_from_source_async(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Versión asíncrona de collect_from_source.
        Por defecto, delega a la versión síncrona usando un hilo.
        """
        return await asyncio.to_thread(self.collect_from_source, source_id, source_config)

    def collect_from_multiple_sources(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Coordina la recolección de múltiples fuentes de manera secuencial."""
        # This is a synchronous wrapper around the logic, but for backward compatibility
        # we can keep the loop here or even reuse the async logic via asyncio.run if appropriate,
        # but to avoid event loop conflicts, we keep the original sync loop logic identical.
        
        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        self.start_time = datetime.now(timezone.utc)
        self._emit_initial_batch_log(len(sources_config))
        self._reset_stats()
        
        source_results: Dict[str, Dict[str, Any]] = {}

        for source_id, source_config in sources_config.items():
            result = self._process_single_source_sync(source_id, source_config)
            source_results[source_id] = result

        return self._finalize_collection_cycle(source_results)

    async def collect_from_multiple_sources_async(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Coordina la recolección de múltiples fuentes de manera asíncrona (paralela)."""
        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        self.start_time = datetime.now(timezone.utc)
        self._emit_initial_batch_log(len(sources_config))
        self._reset_stats()

        tasks = []
        for source_id, source_config in sources_config.items():
            tasks.append(self._process_single_source_async(source_id, source_config))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        source_results = {}
        for source_id, result in zip(sources_config.keys(), results):
            if isinstance(result, Exception):
                # Fallback for unexpected task failures
                error_res = self._create_error_result(source_id, result)
                source_results[source_id] = error_res
                self.stats["total_errors"] += 1
            else:
                 source_results[source_id] = result

        return self._finalize_collection_cycle(source_results)

    # --- Internal Helpers for Code Reuse ---

    def _emit_initial_batch_log(self, count):
        self._emit_log(
            "info",
            "collector.batch.start",
            latency=0.0,
            details={"sources": count},
        )

    def _finalize_collection_cycle(self, source_results):
        end_time = datetime.now(timezone.utc)
        self.stats["processing_time_seconds"] = (
            end_time - (self.start_time or end_time)
        ).total_seconds()

        self._post_process_collection(source_results)
        final_report = self._generate_collection_report(source_results)

        self._emit_log(
            "info",
            "collector.batch.completed",
            latency=self.stats["processing_time_seconds"],
            details={
                "articles_saved": self.stats["total_articles_saved"],
                "articles_found": self.stats["total_articles_found"],
                "sources_processed": self.stats["total_sources_processed"],
                "errors": self.stats["total_errors"],
            },
        )
        self._reset_runtime_context()
        return final_report

    def _process_single_source_sync(self, source_id, source_config):
        try:
            self._pre_process_source(source_id, source_config)
            source_result = self.collect_from_source(source_id, source_config)
            self._update_global_stats(source_result)
            self._post_process_source(source_id, source_config, source_result)
            self._emit_source_log(source_id, source_result)
            return source_result
        except Exception as exc:
            return self._handle_source_exception(source_id, exc)

    async def _process_single_source_async(self, source_id, source_config):
        try:
            # Note: _pre_process_source might be sync, but it's usually fast. 
            # If it were heavy, we'd need to asyncify it too.
            self._pre_process_source(source_id, source_config)
            source_result = await self.collect_from_source_async(source_id, source_config)
            self._update_global_stats(source_result)
            self._post_process_source(source_id, source_config, source_result)
            self._emit_source_log(source_id, source_result)
            return source_result
        except Exception as exc:
            return self._handle_source_exception(source_id, exc)

    def _emit_source_log(self, source_id, source_result):
        event_name = (
            "collector.source.completed"
            if source_result.get("success", False)
            else "collector.source.failed"
        )
        level = "info" if source_result.get("success", False) else "warning"
        self._emit_log(
            level,
            event_name,
            source_id=source_id,
            latency=float(source_result.get("processing_time") or 0.0),
            details={
                "articles_found": source_result.get("articles_found", 0),
                "articles_saved": source_result.get("articles_saved", 0),
                "error_message": source_result.get("error_message"),
            },
        )

    def _handle_source_exception(self, source_id, exc):
        error_result = self._create_error_result(source_id, exc)
        self.stats["total_errors"] += 1
        self._emit_log(
            "error",
            "collector.source.exception",
            source_id=source_id,
            details={"error": str(exc)},
        )
        return error_result

    def _create_error_result(self, source_id, exc):
        return {
            "source_id": source_id,
            "success": False,
            "articles_found": 0,
            "articles_saved": 0,
            "error_message": f"Error inesperado: {exc}",
            "processing_time": 0.0,
        }

    def set_logger_factory(self, logger_factory: "NewsCollectorLogger") -> None:
        """Actualiza la fábrica de loggers reutilizando el mismo módulo."""

        self.logger_factory = logger_factory
        self.module_logger = self.logger_factory.create_module_logger(
            f"collectors.{self.collector_type.lower()}"
        )

    def _set_runtime_context(
        self, *, session_id: Optional[str], trace_id: Optional[str]
    ) -> None:
        """Asigna contexto transitorio para logs estructurados."""

        self._active_session_id = session_id
        self._active_trace_id = trace_id

    def _reset_runtime_context(self) -> None:
        """Limpia el contexto una vez finalizado el batch."""

        self._active_session_id = None
        self._active_trace_id = None

    def _build_log_payload(
        self,
        event: str,
        *,
        source_id: Optional[str] = None,
        article_id: Optional[str] = None,
        latency: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crea un payload consistente para logs estructurados."""

        payload: Dict[str, Any] = {
            "event": event,
            "trace_id": trace_id if trace_id is not None else self._active_trace_id,
            "session_id": (
                session_id if session_id is not None else self._active_session_id
            ),
            "source_id": source_id,
            "article_id": article_id,
            "collector_type": self.collector_type,
            "latency": latency,
        }

        if details:
            payload["details"] = details

        return {key: value for key, value in payload.items() if value is not None}

    def _emit_log(
        self,
        level: str,
        event: str,
        *,
        source_id: Optional[str] = None,
        article_id: Optional[str] = None,
        latency: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Emite logs estructurados garantizando campos de correlación."""

        payload = self._build_log_payload(
            event,
            source_id=source_id,
            article_id=article_id,
            latency=latency,
            details=details,
            trace_id=trace_id,
            session_id=session_id,
        )

        log_method = getattr(self.module_logger, level, None)
        if callable(log_method):
            log_method(payload)
        else:  # pragma: no cover - defensive
            self.module_logger.info(payload)

    def _reset_stats(self):
        """
        Resetea las estadísticas para una nueva sesión de recolección.
        """
        self.stats = {
            "total_sources_processed": 0,
            "total_articles_found": 0,
            "total_articles_saved": 0,
            "total_errors": 0,
            "processing_time_seconds": 0,
        }

    def _update_global_stats(self, source_result: Dict[str, Any]):
        """
        Actualiza las estadísticas globales con el resultado de una fuente.

        Este método es como tener un contador centralizado que lleva registro
        de cada evento que va sucediendo durante la recolección.
        """
        self.stats["total_sources_processed"] += 1
        self.stats["total_articles_found"] += source_result.get("articles_found", 0)
        self.stats["total_articles_saved"] += source_result.get("articles_saved", 0)

        if not source_result.get("success", False):
            self.stats["total_errors"] += 1

    def _generate_collection_report(
        self, source_results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Genera un reporte comprehensivo de la sesión de recolección.

        Este reporte es como un informe ejecutivo que resume cada hito que
        aconteció durante la expedición de recolección de información.
        """
        # Calcular métricas derivadas
        success_rate = 0
        if self.stats["total_sources_processed"] > 0:
            successful_sources = sum(1 for r in source_results.values() if r["success"])
            success_rate = (
                successful_sources / self.stats["total_sources_processed"]
            ) * 100

        save_rate = 0
        if self.stats["total_articles_found"] > 0:
            save_rate = (
                self.stats["total_articles_saved"] / self.stats["total_articles_found"]
            ) * 100

        # Identificar mejores y peores fuentes
        best_sources = sorted(
            [
                (source_id, result)
                for source_id, result in source_results.items()
                if result["success"]
            ],
            key=lambda x: x[1]["articles_saved"],
            reverse=True,
        )[:5]

        failed_sources = [
            (source_id, result)
            for source_id, result in source_results.items()
            if not result["success"]
        ]

        # Generar reporte final
        report = {
            "collection_summary": {
                "collector_type": self.collector_type,
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": self.stats["processing_time_seconds"],
                "sources_processed": self.stats["total_sources_processed"],
                "articles_found": self.stats["total_articles_found"],
                "articles_saved": self.stats["total_articles_saved"],
                "errors_encountered": self.stats["total_errors"],
                "success_rate_percent": round(success_rate, 2),
                "save_rate_percent": round(save_rate, 2),
            },
            "source_details": source_results,
            "top_performers": [
                {
                    "source_id": source_id,
                    "articles_saved": result["articles_saved"],
                    "articles_found": result["articles_found"],
                    "efficiency": round(
                        (result["articles_saved"] / max(result["articles_found"], 1))
                        * 100,
                        1,
                    ),
                }
                for source_id, result in best_sources
            ],
            "failed_sources": [
                {"source_id": source_id, "error_message": result["error_message"]}
                for source_id, result in failed_sources
            ],
            "recommendations": self._generate_recommendations(source_results),
        }

        return report

    # Idempotency helpers
    # ===================
    def _make_job_key(self, source_id: str, target: str) -> str:
        raw = f"{self.collector_type}|{source_id}|{target}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_duplicate_job(self, job_key: str) -> bool:
        return job_key in self._job_keys_seen

    def _register_job(self, job_key: str) -> None:
        self._job_keys_seen.add(job_key)

    # Robots/TOS helpers
    # ==================
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
            # Use a short timeout for robots.txt to avoid blocking
            resp = httpx.get(
                robots_url,
                timeout=5.0,
                headers={"User-Agent": COLLECTION_CONFIG["user_agent"]},
                follow_redirects=True,
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
        try:
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
        except Exception:
            # Fail open if URL parsing fails
            return (True, None)

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

    # Dead-letter queue
    # =================
    def _send_to_dlq(
        self,
        source_id: str,
        url: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_hash = hashlib.sha256(
            f"{source_id}|{url}|{ts}".encode("utf-8")
        ).hexdigest()[:12]
        path = Path(DLQ_DIR) / f"{self.collector_type}_{source_id}_{safe_hash}.json"
        payload = {
            "timestamp": ts,
            "collector": self.collector_type,
            "source_id": source_id,
            "url": url,
            "reason": reason,
            "context": context or {},
        }
        try:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            # Best-effort DLQ
            self._emit_log(
                "error",
                "collector.dlq.write_failed",
                source_id=source_id,
                details={"error": str(exc), "path": str(path)},
            )
        return path

    def _save_article(
        self, article_data: CollectorArticleModel | Dict[str, Any]
    ) -> bool:
        """
        Guarda un artículo procesado en la base de datos.
        """
        if isinstance(article_data, CollectorArticleModel):
            title = article_data.title
            source_id = article_data.source_id
            url_value = str(article_data.url)
        else:
            title = article_data.get("title", "sin título")
            source_id = article_data.get("source_id")
            url_value = article_data.get("url")

        try:
            saved_article = self.db_manager.save_article(article_data)
            if saved_article:
                self._emit_log(
                    "info",
                    "collector.article.saved",
                    source_id=source_id,
                    article_id=getattr(saved_article, "id", None),
                    details={
                        "title": title[:120],
                        "url": getattr(saved_article, "url", url_value),
                    },
                )
                return True

            self._emit_log(
                "debug",
                "collector.article.duplicate",
                source_id=source_id,
                details={"title": title[:120], "url": url_value},
            )
            return False

        except ValueError as exc:
            self._emit_log(
                "error",
                "collector.article.save_validation_error",
                source_id=source_id,
                details={"error": str(exc), "title": title[:120]},
            )
            return False
        except Exception as exc:
            self._emit_log(
                "error",
                "collector.article.save_exception",
                source_id=source_id,
                details={"error": str(exc), "title": title[:120]},
            )
            return False

    def _update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        """
        Actualiza las estadísticas de una fuente después de la recolección.
        """
        try:
            self.db_manager.update_source_stats(source_id, stats)
        except Exception as exc:
            self._emit_log(
                "error",
                "collector.source.stats_update_failed",
                source_id=source_id,
                details={"error": str(exc)},
            )

    def _validate_article_data(self, article_data: Dict[str, Any]) -> bool:
        """
        Valida que un artículo tenga la información mínima necesaria.
        """
        # Verificaciones básicas
        if not article_data.get("title") or len(article_data["title"].strip()) < 10:
            return False

        if not article_data.get("url") or not article_data["url"].startswith("http"):
            return False

        # Verificar que el contenido no sea demasiado corto
        # Check 'content' first (full_text), fallback to 'summary'
        text_to_check = article_data.get("content") or article_data.get("summary", "")
        if len(text_to_check) < TEXT_PROCESSING_CONFIG["min_content_length"]:
            return False

        # Verificar que no sea spam o clickbait obvio
        title_lower = article_data["title"].lower()
        penalty_keywords = TEXT_PROCESSING_CONFIG["penalty_keywords"]

        if any(keyword.lower() in title_lower for keyword in penalty_keywords):
            self._emit_log(
                "debug",
                "collector.article.penalty_keyword_rejected",
                source_id=article_data.get("source_id"),
                details={"title": article_data["title"]},
            )
            return False

        return True

    def _clean_text(self, text: str) -> str:
        """
        Limpia y normaliza texto de manera consistente.
        """
        if not text:
            return ""

        from news_collector.utils.text_cleaner import normalize_text

        return normalize_text(text)

    def _generate_recommendations(
        self, source_results: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        """
        Genera recomendaciones basadas en los resultados de la recolección.

        Este método es como tener un analista experto que revisa todos los
        resultados y sugiere mejoras para futuras recolecciones.
        """
        recommendations = []

        # Analizar fuentes que fallan consistentemente
        failed_sources = [s for s, r in source_results.items() if not r["success"]]
        if len(failed_sources) > len(source_results) * 0.2:  # Más del 20% falló
            recommendations.append(
                f"🔧 Revisar configuración de fuentes - {len(failed_sources)} fuentes fallaron"
            )

        # Analizar eficiencia de guardado
        total_found = sum(r["articles_found"] for r in source_results.values())
        total_saved = sum(r["articles_saved"] for r in source_results.values())

        if (
            total_found > 0 and (total_saved / total_found) < 0.5
        ):  # Menos del 50% guardado
            recommendations.append(
                "📊 Baja tasa de guardado - revisar criterios de filtrado y deduplicación"
            )

        # Analizar fuentes sin nuevos artículos
        empty_sources = [
            s
            for s, r in source_results.items()
            if r["success"] and r["articles_found"] == 0
        ]
        if empty_sources:
            recommendations.append(
                f"📭 {len(empty_sources)} fuentes sin artículos nuevos - considerar ajustar frecuencia"
            )

        # Analizar tiempo de procesamiento
        if self.stats["processing_time_seconds"] > 300:  # Más de 5 minutos
            recommendations.append(
                "⏱️ Tiempo de procesamiento alto - considerar paralelización o optimización"
            )

        return recommendations

    # Hooks que pueden ser overrideados por subclases
    # ===============================================

    def _pre_process_source(self, source_id: str, source_config: Dict[str, Any]):
        """
        Hook llamado antes de procesar cada fuente.
        Las subclases pueden override esto para lógica específica.
        """
        pass

    def _post_process_source(
        self,
        source_id: str,
        source_config: Dict[str, Any],
        source_result: Dict[str, Any],
    ):
        """
        Hook llamado después de procesar cada fuente.
        Las subclases pueden override esto para lógica específica.
        """
        pass

    def _post_process_collection(self, source_results: Dict[str, Dict[str, Any]]):
        """
        Hook llamado después de procesar todas las fuentes.
        Las subclases pueden override esto para lógica específica.
        """
        pass

    # Métodos de utilidad comunes
    # ===========================

    def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene las estadísticas actuales del colector.
        """
        return self.stats.copy()

    def is_healthy(self) -> bool:
        """
        Determina si el colector está en estado saludable.

        Un colector se considera saludable si no ha tenido demasiados errores
        y está procesando fuentes de manera efectiva.
        """
        if self.stats["total_sources_processed"] == 0:
            return True  # No ha procesado nada aún

        error_rate = self.stats["total_errors"] / self.stats["total_sources_processed"]
        return error_rate < 0.3  # Menos del 30% de errores

    def get_performance_metrics(self) -> Dict[str, float]:
        """
        Calcula métricas de performance del colector.

        Estas métricas son útiles para monitoreo y optimización del sistema.
        """
        if self.stats["processing_time_seconds"] == 0:
            return {}

        return {
            "sources_per_minute": (
                self.stats["total_sources_processed"]
                / max(self.stats["processing_time_seconds"] / 60, 1)
            ),
            "articles_per_minute": (
                self.stats["total_articles_found"]
                / max(self.stats["processing_time_seconds"] / 60, 1)
            ),
            "success_rate": (
                (self.stats["total_sources_processed"] - self.stats["total_errors"])
                / max(self.stats["total_sources_processed"], 1)
            ),
            "efficiency_rate": (
                self.stats["total_articles_saved"]
                / max(self.stats["total_articles_found"], 1)
            ),
        }


# Funciones de utilidad para trabajar con colectores
# =================================================


def create_collector(collector_type: str) -> BaseCollector:
    """
    Factory function para crear colectores según el tipo.

    Esta función es como tener un gerente de personal que sabe exactamente
    qué tipo de especialista necesitas para cada trabajo específico.
    """
    if collector_type.lower() == "rss":
        from .rss_collector import RSSCollector
        return RSSCollector()
    elif collector_type.lower() == "html":
        from .html_collector import HtmlCollector
        return HtmlCollector()
    elif collector_type.lower() == "async_rss":
        from .async_rss_collector import AsyncRSSCollector
        return AsyncRSSCollector()
    else:
        raise ValueError(f"Tipo de colector no soportado: {collector_type}")


def validate_collector_result(result: Dict[str, Any]) -> bool:
    """
    Valida que un resultado de colector tenga la estructura esperada.

    Esta función es como un inspector de calidad que verifica que
    cada resultado cumpla con nuestros estándares mínimos.
    """
    required_fields = ["source_id", "success", "articles_found", "articles_saved"]

    return all(field in result for field in required_fields)
