# main.py
# Punto de entrada principal del News Collector System
# ==================================================

"""
Este es el cerebro coordinador de nuestro News Collector System.

Es como el director de una orquesta sinfónica que conoce perfectamente
cada instrumento (módulo) y sabe exactamente cuándo y cómo hacer que
cada uno contribuya para crear una hermosa sinfonía de recopilación
de noticias científicas.

Este archivo coordina:
- Configuración del sistema
- Inicialización de componentes
- Ejecución de recolección
- Procesamiento y scoring
- Generación de reportes

Todo esto de manera robusta, observable, y extensible.
"""

import argparse
import asyncio
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Importar nuestros componentes
from config import (
    ALL_SOURCES,
    validate_config,
    validate_sources,
    COLLECTION_CONFIG,
    SCORING_CONFIG,
)
from src import RSSCollector, get_database_manager, setup_logging, get_metrics_reporter


class NewsCollectorSystem:
    """
    Clase principal que coordina todo el sistema de recopilación de noticias.

    Esta clase es como el CEO de una empresa que conoce todos los departamentos
    y puede dirigir la operación completa de manera eficiente y coordinada.
    """

    def __init__(self, config_override: Optional[Dict[str, Any]] = None):
        """
        Inicializa el sistema completo.

        Args:
            config_override: Configuración opcional para override de defaults
        """
        self.system_id = str(uuid.uuid4())[:8]
        self.start_time = datetime.now(timezone.utc)
        self.config_override = config_override or {}

        # Componentes principales
        self.db_manager = None
        self.collector = None
        self.scorer = None
        self.logger = None
        self.system_logger = None
        self.metrics = None

        # Estado del sistema
        self.is_initialized = False
        self.current_session = None

        print(f"🎯 Inicializando News Collector System (ID: {self.system_id})")

    def initialize(self) -> bool:
        """
        Inicializa todos los componentes del sistema.

        Esta función es como preparar todo el equipo antes de una expedición:
        verificar que tengamos todo lo necesario, que funcione correctamente,
        y que estemos listos para la aventura.

        Returns:
            True si la inicialización fue exitosa, False en caso contrario
        """
        trace_id = str(uuid.uuid4())
        init_session_id = f"init-{self.system_id}"
        start = time.perf_counter()

        try:
            self._setup_logging()
            init_logger = self.system_logger or self.logger.create_module_logger("system")

            init_logger.info(
                {
                    "event": "system.initialize.start",
                    "trace_id": trace_id,
                    "session_id": init_session_id,
                    "source_id": "system",
                    "latency": 0.0,
                    "details": {"system_id": self.system_id},
                }
            )

            self._setup_metrics()

            self._validate_configuration()
            init_logger.info(
                {
                    "event": "system.configuration.validated",
                    "trace_id": trace_id,
                    "session_id": init_session_id,
                    "source_id": "system",
                    "latency": 0.0,
                    "details": {"override_count": len(self.config_override)},
                }
            )

            self._setup_database()
            self._setup_collectors()
            self._setup_scoring()

            health_status = self._check_system_health()

            if not health_status["healthy"]:
                raise Exception(f"Sistema no saludable: {health_status['issues']}")

            if health_status.get("warnings"):
                init_logger.warning(
                    {
                        "event": "system.initialize.warning",
                        "trace_id": trace_id,
                        "session_id": init_session_id,
                        "source_id": "system",
                        "latency": 0.0,
                        "details": {"warnings": health_status["warnings"]},
                    }
                )

            self.is_initialized = True

            self.logger.log_system_startup(
                version="1.0.0",
                config_summary={
                    "sources_configured": len(ALL_SOURCES),
                    "database_type": self.db_manager.config["type"],
                    "collection_interval": COLLECTION_CONFIG["collection_interval"],
                    "min_score_threshold": SCORING_CONFIG["minimum_score"],
                },
            )

            init_logger.info(
                {
                    "event": "system.initialize.completed",
                    "trace_id": trace_id,
                    "session_id": init_session_id,
                    "source_id": "system",
                    "latency": time.perf_counter() - start,
                    "details": {"system_id": self.system_id},
                }
            )

            return True

        except Exception as e:
            if self.logger:
                self.logger.log_error_with_context(
                    e,
                    {
                        "system_id": self.system_id,
                        "initialization_phase": "failed",
                        "trace_id": trace_id,
                        "session_id": init_session_id,
                    },
                )
            return False

    def run_collection_cycle(
        self,
        sources_filter: Optional[List[str]] = None,
        dry_run: bool = False,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo de recolección de noticias.

        Esta función es como dirigir una expedición completa: salir a buscar
        información, procesarla, evaluarla, y traer de vuelta solo lo mejor.

        Args:
            sources_filter: Lista opcional de IDs de fuentes específicas a procesar
            dry_run: Si True, simula la ejecución sin guardar en base de datos

        Returns:
            Diccionario con resultados detallados del ciclo
        """
        if not self.is_initialized:
            raise RuntimeError(
                "Sistema no inicializado. Ejecutar initialize() primero."
            )

        trace_id = trace_id or str(uuid.uuid4())

        session_id = (
            f"{self.system_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        self.current_session = session_id

        session_logger = self.logger.create_module_logger(f"session.{session_id}")
        cycle_start = time.perf_counter()

        session_logger.info(
            {
                "event": "collection_cycle.start",
                "trace_id": trace_id,
                "session_id": session_id,
                "source_id": "system",
                "latency": 0.0,
                "details": {
                    "dry_run": dry_run,
                    "source_filter": sources_filter or "all",
                },
            }
        )

        try:
            sources_to_process = self._get_sources_to_process(sources_filter)
            session_logger.info(
                {
                    "event": "collection_cycle.sources.selected",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "source_id": "system",
                    "latency": 0.0,
                    "details": {"count": len(sources_to_process)},
                }
            )

            collection_results = self._execute_collection(sources_to_process, dry_run)
            self._record_collection_observability(
                collection_results, session_id=session_id, trace_id=trace_id
            )

            scoring_results = self._execute_scoring(collection_results, dry_run)
            session_logger.info(
                {
                    "event": "collection_cycle.scoring.completed",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "source_id": "system",
                    "latency": 0.0,
                    "details": scoring_results.get("statistics", {}),
                }
            )

            final_selection = self._execute_final_selection(scoring_results)
            final_report = self._generate_session_report(
                collection_results, scoring_results, final_selection, session_id
            )

            self.logger.log_performance_metrics(
                final_report["performance_metrics"], "CICLO COMPLETO"
            )

            session_logger.info(
                {
                    "event": "collection_cycle.completed",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "source_id": "system",
                    "latency": time.perf_counter() - cycle_start,
                    "details": final_report["summary"],
                }
            )

            return final_report

        except Exception as e:
            session_logger.error(
                {
                    "event": "collection_cycle.error",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "source_id": "system",
                    "latency": time.perf_counter() - cycle_start,
                    "details": {"error": str(e)},
                }
            )
            self.logger.log_error_with_context(
                e, {"session_id": session_id, "system_id": self.system_id, "trace_id": trace_id}
            )
            raise

    def get_top_articles(
        self, limit: int = 10, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene los mejores artículos según scoring.

        Args:
            limit: Número máximo de artículos a retornar
            category: Categoría opcional para filtrar

        Returns:
            Lista de artículos con mejor score
        """
        if not self.is_initialized:
            raise RuntimeError("Sistema no inicializado")

        try:
            if category:
                articles = self.db_manager.get_articles_by_category(category)
            else:
                articles = self.db_manager.get_articles_by_score(limit)

            articles_dicts = [article.to_dict() for article in articles]

            from src.reranker import rerank_articles

            reranked = rerank_articles(
                articles_dicts,
                limit=limit,
                source_cap_percentage=SCORING_CONFIG.get("source_cap_percentage", 0.5),
                topic_cap_percentage=SCORING_CONFIG.get("topic_cap_percentage", 0.5),
                seed=SCORING_CONFIG.get("reranker_seed", 42),
            )

            return reranked

        except Exception as e:
            self.logger.log_error_with_context(
                e,
                {"operation": "get_top_articles", "limit": limit, "category": category},
            )
            raise

    def get_system_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas completas del sistema.

        Returns:
            Diccionario con estadísticas detalladas
        """
        if not self.is_initialized:
            raise RuntimeError("Sistema no inicializado")

        try:
            # Estadísticas de base de datos
            db_health = self.db_manager.get_health_status()
            daily_stats = self.db_manager.get_daily_stats()
            source_performance = self.db_manager.get_top_sources_performance()

            # Estadísticas del sistema
            system_uptime = (
                datetime.now(timezone.utc) - self.start_time
            ).total_seconds()

            return {
                "system_info": {
                    "system_id": self.system_id,
                    "start_time": self.start_time.isoformat(),
                    "uptime_seconds": system_uptime,
                    "is_healthy": db_health.get("status") == "healthy",
                },
                "database_health": db_health,
                "daily_statistics": daily_stats,
                "source_performance": source_performance,
                "configuration": {
                    "total_sources": len(ALL_SOURCES),
                    "collection_interval_hours": COLLECTION_CONFIG[
                        "collection_interval"
                    ],
                    "minimum_score": SCORING_CONFIG["minimum_score"],
                    "daily_target": SCORING_CONFIG["daily_top_count"],
                },
            }

        except Exception as e:
            self.logger.log_error_with_context(
                e, {"operation": "get_system_statistics"}
            )
            raise

    # Métodos privados de inicialización
    # ==================================

    def _setup_logging(self):
        """Configura el sistema de logging."""
        self.logger = setup_logging()
        self.system_logger = self.logger.create_module_logger("system")

        # Log información del sistema al inicio
        self.logger.log_system_health()

    def _setup_metrics(self) -> None:
        """Inicializa el emisor de métricas del sistema."""
        if self.metrics is None:
            self.metrics = get_metrics_reporter()

    def _validate_configuration(self):
        """Valida toda la configuración del sistema."""
        # Validar configuración general
        validate_config()

        # Validar fuentes
        validate_sources()

        # Aplicar overrides si existen
        if self.config_override:
            self.logger.create_module_logger("config").info(
                f"Aplicando {len(self.config_override)} overrides de configuración"
            )

    def _setup_database(self):
        """Inicializa el sistema de base de datos."""
        self.db_manager = get_database_manager()

        # Inicializar fuentes en la base de datos
        self.db_manager.initialize_sources(ALL_SOURCES)

        self.logger.create_module_logger("database").info("Base de datos configurada")

    def _setup_collectors(self):
        """Configura los colectores del sistema."""
        try:
            if COLLECTION_CONFIG.get("async_enabled"):
                from src.collectors.async_rss_collector import AsyncRSSCollector

                self.collector = AsyncRSSCollector()
            else:
                self.collector = RSSCollector()
        except Exception:
            # Fallback seguro
            self.collector = RSSCollector()

        self.logger.create_module_logger("collectors").info("Colectores configurados")

    def _setup_scoring(self):
        """Configura el sistema de scoring."""
        from src.scoring import create_scorer

        weights_override = self.config_override.get("scoring_weights")
        mode_override = self.config_override.get("scoring_mode")
        self.scorer = create_scorer(weights_override, mode=mode_override)

        self.logger.create_module_logger("scoring").info(
            "Sistema de scoring configurado",
        )

    def _check_system_health(self) -> Dict[str, Any]:
        """
        Verifica la salud general del sistema.

        Returns:
            Diccionario con estado de salud y posibles issues
        """
        issues: List[str] = []
        warnings: List[str] = []
        critical_issues: List[str] = []

        # Verificar base de datos
        try:
            db_health = self.db_manager.get_health_status()
            if db_health.get("failed_sources", 0) > 0:
                warning_message = f"{db_health['failed_sources']} fuentes fallando"
                warnings.append(warning_message)
                issues.append(warning_message)

                # Registrar la advertencia para visibilidad operativa
                self.logger.create_module_logger("database").warning(
                    {
                        "event": "database.health.warning",
                        "trace_id": None,
                        "session_id": None,
                        "source_id": "database",
                        "latency": 0.0,
                        "details": {"failed_sources": db_health["failed_sources"]},
                    }
                )
        except Exception as e:
            issue_message = f"Error verificando base de datos: {str(e)}"
            issues.append(issue_message)
            critical_issues.append(issue_message)
            self.logger.create_module_logger("database").error(
                {
                    "event": "database.health.error",
                    "trace_id": None,
                    "session_id": None,
                    "source_id": "database",
                    "latency": 0.0,
                    "details": {"error": issue_message},
                }
            )

        # Verificar colector
        if not self.collector.is_healthy():
            collector_issue = "Colector en estado no saludable"
            issues.append(collector_issue)
            critical_issues.append(collector_issue)
            self.logger.create_module_logger("collectors").error(
                {
                    "event": "collector.health.error",
                    "trace_id": None,
                    "session_id": None,
                    "source_id": "collectors",
                    "latency": 0.0,
                    "details": {"error": collector_issue},
                }
            )

        # Verificar que tengamos fuentes configuradas
        if len(ALL_SOURCES) == 0:
            config_issue = "No hay fuentes configuradas"
            issues.append(config_issue)
            critical_issues.append(config_issue)
            self.logger.create_module_logger("config").error(
                {
                    "event": "config.health.error",
                    "trace_id": None,
                    "session_id": None,
                    "source_id": "config",
                    "latency": 0.0,
                    "details": {"error": config_issue},
                }
            )

        return {
            "healthy": len(critical_issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "check_time": datetime.now(timezone.utc).isoformat(),
        }

    # Métodos privados de ejecución
    # ============================

    def _get_sources_to_process(
        self, sources_filter: Optional[List[str]]
    ) -> Dict[str, Dict[str, Any]]:
        """Determina qué fuentes procesar en este ciclo."""
        if sources_filter:
            # Filtrar solo las fuentes especificadas
            return {
                source_id: source_config
                for source_id, source_config in ALL_SOURCES.items()
                if source_id in sources_filter
            }
        else:
            # Procesar todas las fuentes
            return ALL_SOURCES.copy()

    def _execute_collection(
        self, sources: Dict[str, Dict[str, Any]], dry_run: bool
    ) -> Dict[str, Any]:
        """Ejecuta la fase de recolección de artículos."""
        if dry_run:
            # En modo dry_run, simular recolección
            return self._simulate_collection(sources)
        else:
            # Recolección real
            if hasattr(self.collector, "collect_from_multiple_sources_async"):
                # Ejecutar versión async si está disponible
                return asyncio.run(
                    self.collector.collect_from_multiple_sources_async(sources)
                )
            return self.collector.collect_from_multiple_sources(sources)

    def _record_collection_observability(
        self, collection_results: Dict[str, Any], session_id: str, trace_id: str
    ) -> None:
        """Loggea resultados por fuente y emite métricas asociadas."""

        source_details = collection_results.get("source_details") or {}
        if not source_details:
            return

        collector_logger = self.logger.create_module_logger("collectors")

        for source_id, result in source_details.items():
            latency = float(result.get("processing_time") or 0.0)
            payload = {
                "event": "collector.source.completed"
                if result.get("success", False)
                else "collector.source.failed",
                "trace_id": trace_id,
                "session_id": session_id,
                "source_id": source_id,
                "latency": latency,
                "details": {
                    "articles_found": result.get("articles_found", 0),
                    "articles_saved": result.get("articles_saved", 0),
                    "error_message": result.get("error_message"),
                },
            }

            if result.get("success", False):
                collector_logger.info(payload)
                if self.metrics:
                    self.metrics.record_ingest(
                        source_id=source_id,
                        article_count=result.get("articles_saved", 0),
                        latency=latency,
                        trace_id=trace_id,
                        session_id=session_id,
                    )
            else:
                collector_logger.warning(payload)
                if self.metrics:
                    self.metrics.record_error(
                        source_id=source_id,
                        error=result.get("error_message", "unknown"),
                        trace_id=trace_id,
                        session_id=session_id,
                    )

    def _execute_scoring(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Ejecuta la fase de scoring de artículos."""
        # Obtener artículos pendientes de scoring
        if dry_run:
            # En modo dry_run, simular scoring
            return self._simulate_scoring(collection_results)
        else:
            # Scoring real
            pending_articles = self.db_manager.get_pending_articles()

            scoring_stats = {
                "articles_scored": 0,
                "articles_included": 0,
                "articles_excluded": 0,
                "average_score": 0.0,
            }

            total_score = 0.0

            from concurrent.futures import ThreadPoolExecutor, as_completed

            max_workers = self.config_override.get(
                "scoring_workers"
            ) or SCORING_CONFIG.get("workers", 4)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self.scorer.score_article,
                        article,
                        ALL_SOURCES.get(article.source_id),
                    ): article
                    for article in pending_articles
                }

                for future in as_completed(futures):
                    article = futures[future]
                    try:
                        score_result = future.result()
                        self.db_manager.update_article_score(article.id, score_result)

                        scoring_stats["articles_scored"] += 1
                        total_score += score_result["final_score"]

                        if score_result["should_include"]:
                            scoring_stats["articles_included"] += 1
                        else:
                            scoring_stats["articles_excluded"] += 1

                    except Exception as e:
                        self.logger.create_module_logger("scoring").error(
                            f"Error scoring artículo {article.id}: {str(e)}"
                        )

            if scoring_stats["articles_scored"] > 0:
                scoring_stats["average_score"] = (
                    total_score / scoring_stats["articles_scored"]
                )

            return {
                "success": True,
                "statistics": scoring_stats,
                "processed_articles": scoring_stats["articles_scored"],
            }

    def _execute_final_selection(
        self, scoring_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ejecuta la selección final de mejores artículos."""
        try:
            # Obtener mejores artículos
            top_articles = self.db_manager.get_articles_by_score(
                limit=SCORING_CONFIG["daily_top_count"],
                min_score=SCORING_CONFIG["minimum_score"],
            )

            # Convertir a formato serializable
            selected_articles = [article.to_dict() for article in top_articles]

            return {
                "success": True,
                "selected_count": len(selected_articles),
                "articles": selected_articles,
                "selection_criteria": {
                    "minimum_score": SCORING_CONFIG["minimum_score"],
                    "target_count": SCORING_CONFIG["daily_top_count"],
                },
            }

        except Exception as e:
            self.logger.log_error_with_context(e, {"operation": "final_selection"})
            return {
                "success": False,
                "error": str(e),
                "selected_count": 0,
                "articles": [],
            }

    def _generate_session_report(
        self,
        collection_results: Dict[str, Any],
        scoring_results: Dict[str, Any],
        selection_results: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """Genera reporte completo de la sesión."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()

        # Consolidar estadísticas
        report = {
            "session_info": {
                "session_id": session_id,
                "system_id": self.system_id,
                "start_time": self.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
            },
            "collection_results": collection_results,
            "scoring_results": scoring_results,
            "selection_results": selection_results,
            "performance_metrics": {
                "total_duration_seconds": duration,
                "articles_per_second": (
                    collection_results.get("collection_summary", {}).get(
                        "articles_found", 0
                    )
                    / max(duration, 1)
                ),
                "sources_per_minute": (
                    collection_results.get("collection_summary", {}).get(
                        "sources_processed", 0
                    )
                    / max(duration / 60, 1)
                ),
                "success_rate_percent": collection_results.get(
                    "collection_summary", {}
                ).get("success_rate_percent", 0),
            },
            "summary": {
                "sources_processed": collection_results.get(
                    "collection_summary", {}
                ).get("sources_processed", 0),
                "articles_found": collection_results.get("collection_summary", {}).get(
                    "articles_found", 0
                ),
                "articles_saved": collection_results.get("collection_summary", {}).get(
                    "articles_saved", 0
                ),
                "articles_scored": scoring_results.get("statistics", {}).get(
                    "articles_scored", 0
                ),
                "final_selection_count": selection_results.get("selected_count", 0),
            },
        }

        return report

    def _simulate_collection(
        self, sources: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Simula recolección para modo dry_run."""
        import random

        simulated_results = {
            "collection_summary": {
                "sources_processed": len(sources),
                "articles_found": random.randint(10, 50),
                "articles_saved": random.randint(5, 25),
                "success_rate_percent": random.uniform(80, 95),
            }
        }

        self.logger.create_module_logger("simulation").info(
            {
                "event": "collection.simulation",
                "trace_id": None,
                "session_id": self.current_session,
                "source_id": "simulation",
                "latency": 0.0,
                "details": {"sources": len(sources)},
            }
        )

        return simulated_results

    def _simulate_scoring(self, collection_results: Dict[str, Any]) -> Dict[str, Any]:
        """Simula scoring para modo dry_run."""
        import random

        articles_found = collection_results.get("collection_summary", {}).get(
            "articles_found", 0
        )

        simulated_scoring = {
            "success": True,
            "statistics": {
                "articles_scored": articles_found,
                "articles_included": random.randint(
                    articles_found // 3, articles_found // 2
                ),
                "articles_excluded": articles_found
                - random.randint(articles_found // 3, articles_found // 2),
                "average_score": random.uniform(0.4, 0.8),
            },
        }

        return simulated_scoring


# Funciones de utilidad para uso externo
# =====================================


def create_system(
    config_override: Optional[Dict[str, Any]] = None,
) -> NewsCollectorSystem:
    """
    Factory function para crear una instancia del sistema.

    Args:
        config_override: Configuración opcional para override

    Returns:
        Instancia configurada del NewsCollectorSystem
    """
    return NewsCollectorSystem(config_override)


def run_quick_collection(
    sources_filter: Optional[List[str]] = None, dry_run: bool = False
) -> Dict[str, Any]:
    """
    Función de conveniencia para ejecutar una recolección rápida.

    Args:
        sources_filter: Lista opcional de fuentes específicas
        dry_run: Si True, simula la ejecución

    Returns:
        Resultados de la recolección
    """
    system = create_system()

    if not system.initialize():
        raise RuntimeError("No se pudo inicializar el sistema")

    return system.run_collection_cycle(sources_filter, dry_run)


def main():
    """
    Función principal para ejecución desde línea de comandos.
    """
    parser = argparse.ArgumentParser(description="News Collector System")
    parser.add_argument("--sources", nargs="+", help="Fuentes específicas a procesar")
    parser.add_argument(
        "--dry-run", action="store_true", help="Simular ejecución sin guardar datos"
    )
    parser.add_argument(
        "--top", type=int, default=10, help="Número de mejores artículos a mostrar"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Mostrar estadísticas del sistema"
    )

    args = parser.parse_args()

    try:
        system = create_system()

        print("🔧 Inicializando sistema...")
        if not system.initialize():
            print("❌ Error durante inicialización")
            sys.exit(1)

        if args.stats:
            print("\n📊 ESTADÍSTICAS DEL SISTEMA:")
            stats = system.get_system_statistics()

            print(f"  • Sistema ID: {stats['system_info']['system_id']}")
            print(f"  • Uptime: {stats['system_info']['uptime_seconds']:.1f} segundos")
            print(
                f"  • Estado: {'Saludable' if stats['system_info']['is_healthy'] else 'Con problemas'}"
            )
            print(
                f"  • Artículos totales: {stats['database_health']['total_articles']}"
            )
            print(f"  • Fuentes activas: {stats['database_health']['active_sources']}")

        else:
            print("\n🚀 Ejecutando ciclo de recolección...")
            results = system.run_collection_cycle(args.sources, args.dry_run)

            print("\n📈 RESUMEN DE RESULTADOS:")
            summary = results["summary"]
            print(f"  • Fuentes procesadas: {summary['sources_processed']}")
            print(f"  • Artículos encontrados: {summary['articles_found']}")
            print(f"  • Artículos guardados: {summary['articles_saved']}")
            print(
                f"  • Artículos en selección final: {summary['final_selection_count']}"
            )

            if args.top > 0 and not args.dry_run:
                print(f"\n⭐ TOP {args.top} ARTÍCULOS:")
                top_articles = system.get_top_articles(args.top)

                for i, article in enumerate(top_articles, 1):
                    print(f"  {i}. {article['title'][:80]}...")
                    print(
                        f"     Score: {article['final_score']:.3f} | Fuente: {article['source_name']}"
                    )

        print("\n✅ Ejecución completada exitosamente!")

    except KeyboardInterrupt:
        print("\n⚠️  Ejecución interrumpida por usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error durante ejecución: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

# ¿Por qué esta arquitectura de main.py?
# =====================================
#
# 1. ORQUESTACIÓN COMPLETA: Coordina todos los componentes del sistema
#    de manera elegante y robusta.
#
# 2. OBSERVABILIDAD TOTAL: Logging detallado de cada fase y operación
#    para facilitar debugging y monitoreo.
#
# 3. MANEJO DE ERRORES: Estrategia robusta para manejar fallos sin
#    corromper datos o dejar el sistema en estado inconsistente.
#
# 4. FLEXIBILIDAD: Soporte para modo dry_run, filtrado de fuentes,
#    y configuración personalizada.
#
# 5. INTERFAZ CLARA: API simple tanto para uso programático como
#    desde línea de comandos.
#
# 6. ESCALABILIDAD: Diseñado para manejar desde pruebas pequeñas
#    hasta operación en producción con miles de artículos.
#
# Este main.py es como tener un director de orquesta experto que puede
# dirigir desde un cuarteto de cámara hasta una sinfonía completa,
# adaptándose perfectamente a cualquier escala de operación.
