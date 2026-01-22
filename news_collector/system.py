"""
News Collector System Definition
================================

Este módulo define la clase central `NewsCollectorSystem` y sus utilidades.
"""

import asyncio
import time
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from news_collector.config import (
    ALL_SOURCES,
    validate_config,
    validate_sources,
    COLLECTION_CONFIG,
    SCORING_CONFIG,
)
from news_collector import RSSCollector, get_database_manager, setup_logging, get_metrics_reporter
from news_collector.validation.validator import ContentValidator


class NewsCollectorSystem:
    """
    Clase principal que coordina la operación completa del sistema de recopilación de noticias.

    Esta clase es como el CEO de una empresa que conoce todos los departamentos
    y puede dirigir la operación completa de manera eficiente y coordinada.
    """

    def __init__(self, config_override: Optional[Dict[str, Any]] = None, health_tracker: Optional[Any] = None):
        """
        Inicializa el sistema completo.

        Args:
            config_override: Configuración opcional para override de defaults
        """
        self.system_id = str(uuid.uuid4())[:8]
        self.start_time = datetime.now(timezone.utc)
        self.start_time = datetime.now(timezone.utc)
        self.config_override = config_override or {}
        self.health_tracker = health_tracker

        # Componentes principales
        self.db_manager = None
        self.collector = None
        self.scorer = None
        self.logger = None
        self.system_logger = None
        self.metrics = None
        self.validator = None

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
            self._setup_logging()
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
            self._setup_validation()
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

            collection_results = await self._execute_collection(
                sources_to_process,
                dry_run,
                session_id=session_id,
                trace_id=trace_id,
            )
            self._record_collection_observability(
                collection_results, session_id=session_id, trace_id=trace_id
            )

            validation_results = self._execute_validation(collection_results, dry_run)
            session_logger.info(
                {
                    "event": "collection_cycle.validation.completed",
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "source_id": "system",
                    "latency": 0.0,
                    "details": {
                        "validated": validation_results.get("validated_count", 0),
                        "rejected": validation_results.get("rejected_count", 0)
                    },
                }
            )

            scoring_results = await self._execute_scoring(collection_results, dry_run)
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

            final_selection = self._execute_final_selection(scoring_results, collection_results)
            final_report = self._generate_session_report(
                collection_results, scoring_results, final_selection, session_id
            )

            self.logger.log_performance_metrics(
                final_report["performance_metrics"], "CICLO COMPLETO"
            )

            # Log informativo solicitado por usuario
            source_details = collection_results.get("source_details", {})
            total_sources = len(source_details)
            sources_with_data = sum(1 for res in source_details.values() if res.get("articles_saved", 0) > 0)
            if self.system_logger:
                self.system_logger.info(f"📊 Reporte de Recolección: {sources_with_data}/{total_sources} fuentes produjeron información con éxito (artículos guardados).")

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
                e,
                {
                    "session_id": session_id,
                    "system_id": self.system_id,
                    "trace_id": trace_id,
                },
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

            from news_collector.reranker import rerank_articles

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

    def export_latest_articles(self, file_path: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Exports the latest top-scored articles to a JSON schema.
        
        Args:
            file_path: Optional path to write the JSON file to.
            limit: Number of articles to export.
            
        Returns:
            The export dictionary payload.
        """
        if not self.is_initialized:
            raise RuntimeError("Sistema no inicializado")

        try:
            # Get articles
            # Note: exclude_published=True allows Refinery to only see what needs work
            articles = self.db_manager.get_articles_by_score(limit=limit, exclude_published=True)
            
            serialized_articles = []
            for art in articles:
                art_dict = {
                    "id": art.id,
                    "title": art.title,
                    "url": art.url,
                    "summary": art.summary,
                    "content": art.content,
                    "source_name": art.source_name,
                    "published_date": art.published_date.isoformat() if art.published_date else None,
                    "published_at": art.published_at.isoformat() if getattr(art, "published_at", None) else None,
                    "published_url": getattr(art, "published_url", None),
                    "collected_date": art.collected_date.isoformat() if art.collected_date else None,
                    "score": art.final_score,
                    "image_url": art.article_metadata.get("image_url") if art.article_metadata else None,
                    "metadata": art.article_metadata,
                    "authors": art.authors,
                    "category": art.category,
                    "components": art.score_components or {}
                }
                serialized_articles.append(art_dict)
        
            export_payload = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "contract": "news_collector.export.v1",
                "article_count": len(serialized_articles),
                "articles": serialized_articles,
            }

            if file_path:
                path_obj = Path(json.dumps(file_path).strip('"')) if not isinstance(file_path, Path) else file_path
                # Ensure we handle the path correctly whether string or Path
                path_obj = Path(file_path)
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                
                with open(path_obj, 'w', encoding='utf-8') as f:
                    json.dump(export_payload, f, indent=2, ensure_ascii=False)
                
                if self.logger:
                    self.logger.create_module_logger("system").info(f"Exported {len(serialized_articles)} articles to {path_obj}")

            return export_payload

        except Exception as e:
            self.logger.log_error_with_context(e, {"operation": "export_latest_articles"})
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
            from news_collector.collectors.dispatcher import CollectorDispatcher
            
            self.collector = CollectorDispatcher(logger_factory=self.logger, health_tracker=self.health_tracker)
            print(f"DEBUG: System created Dispatcher with health_tracker={self.health_tracker} id={id(self.health_tracker) if self.health_tracker else 'None'}")
            self.logger.create_module_logger("collectors").info("Dispatcher de colectores configurado")
            
        except Exception as e:
            self.logger.create_module_logger("collectors").error(
                f"Error fatal configurando colectores: {str(e)}"
            )
            raise

    def _setup_validation(self):
        """Configura el sistema de validación."""
        self.validator = ContentValidator()
        self.logger.create_module_logger("validation").info("Sistema de validación configurado")

    def _setup_scoring(self):
        """Configura el sistema de scoring."""
        from news_collector.scoring import create_scorer

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
            
            class DummyArticle:
                id = 999999
            
            def mock_save(*args, **kwargs):
                return DummyArticle()
                
            self.db_manager.save_article = mock_save

        try:
            # Recolección real (incluso en dry_run, solo evitamos guardar)
            if hasattr(self.collector, "collect_from_multiple_sources_async"):
                # Ejecutar versión async si está disponible
                return await self.collector.collect_from_multiple_sources_async(
                    sources,
                    session_id=session_id,
                    trace_id=trace_id,
                )
            return self.collector.collect_from_multiple_sources(
                sources,
                session_id=session_id,
                trace_id=trace_id,
            )
        finally:
            if original_save:
                self.db_manager.save_article = original_save

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
                "event": (
                    "collector.source.completed"
                    if result.get("success", False)
                    else "collector.source.failed"
                ),
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

    def _execute_validation(self, collection_results: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
        """Ejecuta la fase de validación de artículos recolectados."""
        if dry_run:
            # En dry_run no validamos porque no hay artículos en DB
            return {"success": True, "validated_count": 0, "rejected_count": 0}
            
        pending_articles = self.db_manager.get_pending_articles()
        
        # Convert to list of dicts for validator, keeping reference to object
        articles_to_validate = [article.to_dict() for article in pending_articles]
        # We need content which is sometimes not in to_dict completely or we need to ensure full fields
        # validator uses: content, summary, title. to_dict has them?
        # to_dict has summary, title. Content is missing in to_dict default?
        # Let's check Article.to_dict in models.py. 
        # It does NOT have 'content' in to_dict (line 216 in models.py). 
        # So we must add it manually for validation.
        
        for i, article in enumerate(pending_articles):
            articles_to_validate[i]["content"] = article.content
            
        validation_results = self.validator.validate_batch(articles_to_validate)
        
        rejected_count = 0
        validated_count = len(pending_articles)
        
        # Process invalid articles
        if validation_results["invalid"]:
            from news_collector.storage.models import Article
            
            with self.db_manager.get_session() as session:
                for invalid_item in validation_results["invalid"]:
                    article_data = invalid_item["article"]
                    reason = invalid_item["reason"]
                    rule_name = invalid_item["rule"]
                    
                    # Find and update article
                    article_id = article_data["id"]
                    
                    # We accept that get_session creates a new session, so we need to fetch object again
                    # or merge. Fetching is safer.
                    article = session.query(Article).filter_by(id=article_id).first()
                    if article:
                        article.processing_status = "rejected"
                        article.error_message = f"Validation failed: {rule_name} - {reason}"
                        rejected_count += 1
        
        self.logger.create_module_logger("validation").info(
            {
                "event": "validation.completed",
                "total": validated_count,
                "rejected": rejected_count,
                "valid": validated_count - rejected_count
            }
        )
            
        return {
            "success": True, 
            "validated_count": validated_count, 
            "rejected_count": rejected_count,
            "details": validation_results
        }

    async def _execute_scoring(
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
            
            # Prepare tasks for async execution
            tasks = []
            max_concurrency = self.config_override.get(
                "scoring_workers"
            ) or SCORING_CONFIG.get("workers", 4)
            
            # Reset metrics if supported
            if hasattr(self.scorer, "reset_cycle_metrics"):
                self.scorer.reset_cycle_metrics()

            # Prepare payloads for all articles
            payloads = []
            for article in pending_articles:
                # Convert ORM object to dict for safe thread usage
                article_data = {
                    "id": article.id,
                    "title": article.title,
                    "summary": article.summary,
                    "url": article.url,
                    "published_date": article.published_date,
                    "collected_date": article.collected_date,
                    "source_id": article.source_id,
                    "article_metadata": article.article_metadata or {},
                    "peer_reviewed": article.peer_reviewed,
                    "is_preprint": article.is_preprint,
                    "doi": article.doi,
                    "journal": article.journal,
                    # Content fields
                    "content": article.content,
                    # Fields for feature scorer
                    "duplication_confidence": getattr(article, "duplication_confidence", 0.0),
                    "word_count": getattr(article, "word_count", 0),
                }
                
                payload = {
                    "article": article_data,
                    "source_config": ALL_SOURCES.get(article.source_id)
                }
                payloads.append(payload)

            # Execute Scoring (Batch or Sequential)
            results = []
            if payloads:
                if hasattr(self.scorer, "score_batch_async"):
                    # New Hybrid Batch Scorer
                    try:
                        results = await self.scorer.score_batch_async(payloads)
                    except Exception as e:
                        self.logger.create_module_logger("scoring").error(f"Batch scoring failed: {e}")
                        # Fallback to empty results -> error handling loop below will catch checks
                        results = [e] * len(payloads)
                else:
                    # Legacy Sequential
                    tasks = [self.scorer.score_article_async(p) for p in payloads]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

            if results:
                # results populated above by batch or legacy gathering

                for article, score_result in zip(pending_articles, results):
                    if isinstance(score_result, Exception):
                        self.logger.create_module_logger("scoring").error(
                            f"Error scoring artículo {article.id}: {str(score_result)}"
                        )
                        continue

                    try:
                        self.db_manager.update_article_score(article.id, score_result)

                        scoring_stats["articles_scored"] += 1
                        total_score += score_result["final_score"]

                        if score_result["should_include"]:
                            scoring_stats["articles_included"] += 1
                        else:
                            scoring_stats["articles_excluded"] += 1

                    except Exception as e:
                        self.logger.create_module_logger("scoring").error(
                            f"Error saving score for article {article.id}: {str(e)}"
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
        self, scoring_results: Dict[str, Any], collection_results: Optional[Dict[str, Any]] = None
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
                    "selection_criteria": {
                        "mode": "dry_run_simulation"
                    },
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

        # Generar artículos simulados para validar contrato
        simulated_articles = []
        for i in range(random.randint(5, 15)):
            simulated_articles.append({
                "title": f"Artículo Simulado {i+1}",
                "url": f"https://example.com/article/{i+1}",
                "source_id": "simulation", # Required by Contract
                "published_date": datetime.now(timezone.utc).isoformat(),
                "summary": f"Resumen del artículo simulado {i+1} para pruebas de contrato.",
                "content": "Contenido completo simulado...",
                "author": "Simulador",
                "categories": ["test", "simulation"],
                "tags": ["e2e", "contract"],
                "editorial_score": random.uniform(0.5, 0.9)
            })

        simulated_results = {
            "collection_summary": {
                "sources_processed": len(sources),
                "articles_found": len(simulated_articles),
                "articles_saved": len(simulated_articles), # En simulación asumimos guardado
                "success_rate_percent": random.uniform(80, 95),
            },
            "source_details": {
                "simulation": {
                    "success": True, 
                    "articles_found": len(simulated_articles),
                    "articles_saved": len(simulated_articles)
                }
            },
            "articles": simulated_articles # Para acceso directo en dry-run
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
