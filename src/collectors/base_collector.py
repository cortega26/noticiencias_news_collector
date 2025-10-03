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
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config.settings import DLQ_DIR

from src.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from src.utils.logger import NewsCollectorLogger


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

    @abstractmethod
    def collect_from_source(
        self, source_id: str, source_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Método abstracto que debe implementar cada colector específico.

        Este es el corazón de cada colector: define cómo recopilar información
        de una fuente específica. Cada tipo de colector (RSS, API, etc.)
        implementará este método según sus necesidades particulares.

        Args:
            source_id: Identificador único de la fuente
            source_config: Configuración completa de la fuente

        Returns:
            Diccionario con estadísticas de la recolección:
            {
                'source_id': str,
                'success': bool,
                'articles_found': int,
                'articles_saved': int,
                'error_message': Optional[str],
                'processing_time': float
            }
        """
        pass

    def collect_from_multiple_sources(
        self,
        sources_config: Dict[str, Dict[str, Any]],
        *,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Coordina la recolección de múltiples fuentes de manera estructurada."""

        self._set_runtime_context(session_id=session_id, trace_id=trace_id)
        self.start_time = datetime.now(timezone.utc)

        self._emit_log(
            "info",
            "collector.batch.start",
            latency=0.0,
            details={"sources": len(sources_config)},
        )

        self._reset_stats()
        source_results: Dict[str, Dict[str, Any]] = {}

        for source_id, source_config in sources_config.items():
            try:
                self._pre_process_source(source_id, source_config)
                source_result = self.collect_from_source(source_id, source_config)
                self._update_global_stats(source_result)
                self._post_process_source(source_id, source_config, source_result)
                source_results[source_id] = source_result

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

            except Exception as exc:
                error_result = {
                    "source_id": source_id,
                    "success": False,
                    "articles_found": 0,
                    "articles_saved": 0,
                    "error_message": f"Error inesperado: {exc}",
                    "processing_time": 0.0,
                }
                source_results[source_id] = error_result
                self.stats["total_errors"] += 1

                self._emit_log(
                    "error",
                    "collector.source.exception",
                    source_id=source_id,
                    details={"error": str(exc)},
                )

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
