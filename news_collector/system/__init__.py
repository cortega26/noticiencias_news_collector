"""
News Collector System Definition
================================

Este módulo define la clase central `NewsCollectorSystem` y sus utilidades.
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from news_collector.config import ALL_SOURCES, COLLECTION_CONFIG, SCORING_CONFIG


class NewsCollectorSystem:
    """
    Clase principal que coordina la operación completa del sistema de recopilación de noticias.

    Esta clase es como el CEO de una empresa que conoce todos los departamentos
    y puede dirigir la operación completa de manera eficiente y coordinada.
    """

    def __init__(
        self,
        config_override: Optional[Dict[str, Any]] = None,
        db_path: Optional[str] = None,
        skip_initialization: bool = False,
        system_id: Optional[str] = None,
        health_tracker: Optional[Any] = None,
    ):
        """Inicializa los componentes base del sistema."""
        self.system_id = system_id or str(uuid.uuid4())[:8]
        self.start_time = datetime.now(timezone.utc)
        self.current_session: Optional[str] = None

        from pydantic import ValidationError

        from news_collector.contracts.system import SystemConfigOverrideModel

        if config_override is not None:
            try:
                self.config_override = SystemConfigOverrideModel.model_validate(
                    config_override
                ).model_dump(exclude_none=True)
            except ValidationError as e:
                print(f"⚠️ Invalid system configuration override provided: {e}")
                self.config_override = {}  # Fallback to empty if validation fails
        else:
            self.config_override = {}
        self.health_tracker = health_tracker

        # Componentes principales
        self.db_manager: Any = None
        self.collector: Any = None
        self.scorer: Any = None
        self.logger: Any = None
        self.system_logger: Any = None
        self.metrics: Any = None
        self.validator: Any = None

        # Coordinadores
        self.validation_coordinator: Any = None
        self.scoring_coordinator: Any = None

        # Estado del sistema
        self.is_initialized = False
        self.current_session = None

        print(f"🎯 Inicializando News Collector System (ID: {self.system_id})")

    def initialize(self) -> bool:
        """
        Inicializa todos los componentes del sistema.

        Esta función es como preparar cada pieza del equipo antes de una expedición:
        verificar que tengamos cada recurso necesario, que funcione correctamente,
        y que estemos listos para la aventura.

        Returns:
            True si la inicialización fue exitosa, False en caso contrario
        """
        trace_id = str(uuid.uuid4())
        init_session_id = f"init-{self.system_id}"
        start = time.perf_counter()

        try:
            from news_collector.system import bootstrap

            # 1. Logging
            self.logger, self.system_logger = bootstrap.build_logging(self.system_id)
            init_logger = self.system_logger or self.logger.create_module_logger(
                "system"
            )

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

            # 2. Metrics
            self.metrics = bootstrap.build_metrics()

            # 3. Config
            bootstrap.validate_system_config(self.config_override, self.logger)
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

            # 4. Database
            self.db_manager = bootstrap.build_database(self.logger)

            # 5. Collectors
            self.collector = bootstrap.build_collectors(
                self.logger, self.health_tracker
            )

            # 6. Validation
            self.validator = bootstrap.build_validator(self.logger)

            # 7. Scoring
            self.scorer = bootstrap.build_scorer(self.config_override, self.logger)

            # 8. Health Check
            health_status = bootstrap.check_system_health(
                self.db_manager, self.collector, self.logger, ALL_SOURCES
            )

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

    async def run_collection_cycle(
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
        from news_collector.system import pipeline

        return await pipeline.run_cycle_orchestration(
            self, sources_filter, dry_run, trace_id
        )

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
        from news_collector.system.reporting import get_top_articles as _get_top

        return _get_top(self, limit, category)

    def export_latest_articles(
        self, file_path: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """
        Exports the latest top-scored articles to a JSON schema.

        Args:
            file_path: Optional path to write the JSON file to.
            limit: Number of articles to export.

        Returns:
            The export dictionary payload.
        """
        from news_collector.system.reporting import export_latest_articles as _export

        return _export(self, file_path, limit)

    def get_system_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas completas del sistema.

        Returns:
            Diccionario con estadísticas detalladas
        """
        from news_collector.system.reporting import get_system_statistics as _get_stats

        return _get_stats(self)

    async def shutdown(self):
        """Cierra ordenadamente los componentes del sistema."""
        if self.collector and hasattr(self.collector, "close"):
            if asyncio.iscoroutinefunction(self.collector.close):
                await self.collector.close()
            else:
                self.collector.close()

        if self.db_manager:
            self.db_manager.close()

        if self.system_logger:
            self.system_logger.info("Sistema apagado correctamente.")

        # Shutdown complete

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
            # Skip manual-only and blacklisted sources during scheduled collection runs.
            return cast(
                Dict[str, Dict[str, Any]],
                {
                    source_id: source_config
                    for source_id, source_config in ALL_SOURCES.items()
                    if not source_config.get("manual_only", False)
                    and not source_config.get("blacklisted", False)
                },
            )

    async def _execute_collection(
        self,
        sources: Dict[str, Dict[str, Any]],
        dry_run: bool,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ejecuta la fase de recolección de artículos."""

        # Setup dry_run mock
        original_save = None
        if dry_run:
            original_save = self.db_manager.save_article

            from news_collector.contracts.mock_article import MockArticle

            def mock_save(*args, **kwargs):
                return MockArticle()

            self.db_manager.save_article = mock_save

        try:
            # Recolección real (incluso en dry_run, solo evitamos guardar)
            if hasattr(self.collector, "collect_from_multiple_sources_async"):
                # Ejecutar versión async si está disponible
                return cast(
                    Dict[str, Any],
                    await self.collector.collect_from_multiple_sources_async(
                        sources,
                        session_id=session_id,
                        trace_id=trace_id,
                    ),
                )
            return cast(
                Dict[str, Any],
                self.collector.collect_from_multiple_sources(
                    sources,
                    session_id=session_id,
                    trace_id=trace_id,
                ),
            )
        finally:
            if original_save:
                self.db_manager.save_article = original_save

    def _execute_validation(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Delegates to ValidationCoordinator."""
        if self.validation_coordinator is None:
            from news_collector.validation.coordinator import ValidationCoordinator

            self.validation_coordinator = ValidationCoordinator(
                db_manager=self.db_manager,
                validator=self.validator,
                logger=self.logger,
            )
        return cast(
            Dict[str, Any],
            self.validation_coordinator.execute(collection_results, dry_run),
        )

    async def _execute_scoring(
        self, collection_results: Dict[str, Any], dry_run: bool
    ) -> Dict[str, Any]:
        """Delegates to ScoringCoordinator."""
        if self.scoring_coordinator is None:
            from news_collector.scoring.coordinator import ScoringCoordinator

            self.scoring_coordinator = ScoringCoordinator(
                db_manager=self.db_manager,
                scorer=self.scorer,
                logger=self.logger,
                config_override=self.config_override,
            )
        return cast(
            Dict[str, Any],
            await self.scoring_coordinator.execute(collection_results, dry_run),
        )

    def _execute_final_selection(
        self,
        scoring_results: Dict[str, Any],
        collection_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ejecuta la selección final de mejores artículos."""
        try:
            # Check for simulated articles in dry-run
            if collection_results and "articles" in collection_results:
                # Dry-run simulation mode
                selected_articles = collection_results["articles"]
                return {
                    "success": True,
                    "selected_count": len(selected_articles),
                    "articles": selected_articles,
                    "selection_criteria": {"mode": "dry_run_simulation"},
                }

            # Normal path (Database)
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
        """Delegates to SessionReporter."""
        from news_collector.system.reporter import SessionReporter

        return SessionReporter(self).generate_report(
            collection_results, scoring_results, selection_results, session_id
        )


# Funciones de utilidad para uso externo
# =====================================


def create_system(
    config_override: Optional[Dict[str, Any]] = None,
    health_tracker: Optional[Any] = None,
) -> NewsCollectorSystem:
    """
    Factory function para crear una instancia del sistema.

    Args:
        config_override: Configuración opcional para override
        health_tracker: Tracker opcional para diagnósticos

    Returns:
        Instancia configurada del NewsCollectorSystem
    """
    return NewsCollectorSystem(config_override, health_tracker=health_tracker)


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

    return asyncio.run(system.run_collection_cycle(sources_filter, dry_run))
