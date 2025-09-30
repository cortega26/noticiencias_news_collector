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

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging
import hashlib
import json
from pathlib import Path

from config.settings import DLQ_DIR
from src.utils import get_observability

logger = logging.getLogger(__name__)


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

    def __init__(self):
        """
        Inicialización común para todos los colectores.
        """
        self.collector_type = self.__class__.__name__
        self.start_time = None
        self.stats = {
            "total_sources_processed": 0,
            "total_articles_found": 0,
            "total_articles_saved": 0,
            "total_errors": 0,
            "processing_time_seconds": 0,
        }

        logger.info(f"🚀 Inicializando colector: {self.collector_type}")
        # Idempotency tracking for this run
        self._job_keys_seen = set()
        self.observability = get_observability()

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
        self, sources_config: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Template method que coordina la recolección de múltiples fuentes.

        Este método implementa la lógica común para procesar múltiples fuentes
        de manera ordenada y eficiente. Es como tener un director de orquesta
        que coordina a todos los músicos (fuentes) para crear una sinfonía
        armoniosa de información.
        """
        self.start_time = datetime.now(timezone.utc)
        logger.info(
            f"🎯 Iniciando recolección masiva con {len(sources_config)} fuentes"
        )
        self.observability.log_event(
            stage="ingestion",
            event="batch.start",
            collector=self.collector_type,
            sources=len(sources_config),
        )

        # Resetear estadísticas para esta sesión
        self._reset_stats()

        # Resultados detallados por fuente
        source_results = {}

        # Procesar cada fuente individualmente
        for source_id, source_config in sources_config.items():
            try:
                # Hook pre-procesamiento (puede ser overrideado por subclases)
                self._pre_process_source(source_id, source_config)

                # Recolectar de la fuente específica
                with self.observability.instrument_stage(
                    "ingestion.source",
                    source_id=source_id,
                    collector=self.collector_type,
                ):
                    source_result = self.collect_from_source(
                        source_id, source_config
                    )

                # Actualizar estadísticas globales
                self._update_global_stats(source_result)

                # Hook post-procesamiento (puede ser overrideado por subclases)
                self._post_process_source(source_id, source_config, source_result)

                source_results[source_id] = source_result

                # Log del resultado de esta fuente
                if source_result["success"]:
                    logger.info(
                        f"✅ {source_id}: {source_result['articles_saved']}/{source_result['articles_found']} artículos"
                    )
                else:
                    logger.warning(
                        f"❌ {source_id}: {source_result.get('error_message', 'Error desconocido')}"
                    )

            except Exception as e:
                # Manejar errores a nivel de fuente sin detener todo el proceso
                error_result = {
                    "source_id": source_id,
                    "success": False,
                    "articles_found": 0,
                    "articles_saved": 0,
                    "error_message": f"Error inesperado: {str(e)}",
                    "processing_time": 0,
                }
                source_results[source_id] = error_result
                self.stats["total_errors"] += 1

                logger.error(f"💥 Error crítico procesando {source_id}: {e}")
                self.observability.record_error("ingestion", type(e).__name__)

        # Finalizar y generar reporte
        end_time = datetime.now(timezone.utc)
        self.stats["processing_time_seconds"] = (
            end_time - self.start_time
        ).total_seconds()

        # Hook post-procesamiento global
        self._post_process_collection(source_results)

        # Generar reporte final
        final_report = self._generate_collection_report(source_results)

        self.observability.log_event(
            stage="ingestion",
            event="batch.completed",
            collector=self.collector_type,
            duration_seconds=self.stats["processing_time_seconds"],
            sources_processed=self.stats["total_sources_processed"],
            errors=self.stats["total_errors"],
        )

        logger.info(
            f"🎉 Recolección completada: {self.stats['total_articles_saved']} artículos guardados en {self.stats['processing_time_seconds']:.1f}s"
        )

        return final_report

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
        de todo lo que va sucediendo durante la recolección.
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

        Este reporte es como un informe ejecutivo que resume todo lo que
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
        except Exception:
            # Best-effort DLQ
            logger.exception("No se pudo escribir en DLQ")
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

    # Aquí podríamos agregar otros tipos de colectores en el futuro:
    # elif collector_type.lower() == 'api':
    #     from .api_collector import APICollector
    #     return APICollector()
    # elif collector_type.lower() == 'scraper':
    #     from .web_scraper import WebScraper
    #     return WebScraper()

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


# ¿Por qué esta arquitectura de clase base?
# =========================================
#
# 1. CONSISTENCIA: Todos los colectores siguen el mismo patrón,
#    facilitando mantenimiento y debugging.
#
# 2. EXTENSIBILIDAD: Fácil agregar nuevos tipos de colectores
#    (APIs, web scraping, etc.) sin cambiar el código existente.
#
# 3. REUTILIZACIÓN DE CÓDIGO: La lógica común (estadísticas, reportes,
#    coordinación) se implementa una sola vez.
#
# 4. TEMPLATE METHOD PATTERN: Permite customización específica mientras
#    mantiene un flujo de trabajo consistente.
#
# 5. OBSERVABILIDAD: Sistema robusto de estadísticas y reportes
#    incorporado desde el principio.
#
# 6. MANEJO DE ERRORES: Estrategia consistente para manejar fallos
#    sin detener todo el proceso.
#
# Esta clase base es como crear los cimientos arquitectónicos que
# aseguran que todas las habitaciones de nuestra casa (colectores)
# tengan las mismas características esenciales de calidad y funcionalidad.
