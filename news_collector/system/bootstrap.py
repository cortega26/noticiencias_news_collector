"""
Module role: Encapsulates runtime dependency construction, system startup logic, and initial health checks.

Inputs:
- Configuration overrides and source configurations.
- Environment variables and global config settings.

Outputs:
- Instantiated core components: logger, metrics reporter, database manager, collectors, validator, and scorer.
- System health diagnostic reports.

Side effects:
- Initializes external database connections and ensures sources exist in DB.
- Triggers HTTP calls for external LLM provider health checks.
- Modifies global config state (disables LLM system) if LLM health check fails.

Invariants:
- LAW-3: System Layer Is Orchestration Only. Responsible for wiring dependencies safely, not processing data.
- Must gracefully capture DB/Collector/Config setup errors and reflect them in the health report.
- Must validate system configuration before wiring begins.

Failure modes:
- Database initialization failure surfaces in health report and logs as a critical error.
- Invalid configuration raises validation exceptions and halts bootstrap.
- LLM connectivity failures toggle offline mode instead of crashing out.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from news_collector import get_database_manager, get_metrics_reporter, setup_logging
from news_collector.config import ALL_SOURCES, validate_config, validate_sources
from news_collector.validation.validator import ContentValidator

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _is_smoke_mode_enabled() -> bool:
    return os.getenv("NOTICIENCIAS_SMOKE", "").strip().lower() in _TRUTHY_VALUES


def build_logging(system_id: str):
    """Configura el sistema de logging."""
    logger = setup_logging()
    system_logger = logger.create_module_logger("system")
    # Log información del sistema al inicio
    logger.log_system_health()
    return logger, system_logger


def build_metrics():
    """Inicializa el emisor de métricas del sistema."""
    return get_metrics_reporter()


def _resolve_module_logger(logger: Any, name: str = "system") -> Any:
    if logger is None:
        return None
    if hasattr(logger, "create_module_logger"):
        return logger.create_module_logger(name)
    return logger


def validate_system_config(
    config_override: Optional[Dict[str, Any]] = None, logger: Any = None
):
    """Valida toda la configuración del sistema."""
    # Validar configuración general
    validate_config()

    # Validar fuentes
    validate_sources()

    # Aplicar overrides si existen
    if config_override and logger:
        logger.create_module_logger("config").info(
            f"Aplicando {len(config_override)} overrides de configuración"
        )


def build_database(logger: Any):
    """Inicializa el sistema de base de datos."""
    db_manager = get_database_manager()
    # Inicializar fuentes en la base de datos
    db_manager.initialize_sources(ALL_SOURCES)
    if logger:
        logger.create_module_logger("database").info("Base de datos configurada")
    return db_manager


def build_collectors(logger: Any, health_tracker: Any):
    """Configura los colectores del sistema."""
    try:
        from news_collector.collectors.dispatcher import CollectorDispatcher

        collector = CollectorDispatcher(
            logger_factory=logger, health_tracker=health_tracker
        )
        print(
            f"DEBUG: System created Dispatcher with health_tracker={health_tracker} id={id(health_tracker) if health_tracker else 'None'}"
        )
        if logger:
            logger.create_module_logger("collectors").info(
                "Dispatcher de colectores configurado"
            )
        return collector

    except Exception as e:
        if logger:
            logger.create_module_logger("collectors").error(
                f"Error fatal configurando colectores: {str(e)}"
            )
        raise


def build_validator(logger: Any):
    """Configura el sistema de validación."""
    validator = ContentValidator()
    if logger:
        logger.create_module_logger("validation").info(
            "Sistema de validación configurado"
        )
    return validator


def build_scorer(config_override: Dict[str, Any], logger: Any):
    """Configura el sistema de scoring."""
    from news_collector.scoring import create_scorer

    weights_override = config_override.get("scoring_weights")
    mode_override = config_override.get("scoring_mode")
    scorer = create_scorer(weights_override, mode=mode_override)

    if logger:
        logger.create_module_logger("scoring").info(
            "Sistema de scoring configurado",
        )
    return scorer


def check_system_health(
    db_manager: Any, collector: Any, logger: Any, sources_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Verifica la salud general del sistema.
    """
    issues: List[str] = []
    warnings: List[str] = []
    critical_issues: List[str] = []

    # Verificar base de datos
    try:
        db_health = db_manager.get_health_status()
        if db_health.get("failed_sources", 0) > 0:
            failed_sources = db_health["failed_sources"]
            warning_message = (
                f"{failed_sources} fuente fallando"
                if failed_sources == 1
                else f"{failed_sources} fuentes fallando"
            )
            warnings.append(warning_message)
            issues.append(warning_message)

            # Registrar la advertencia para visibilidad operativa
            logger.create_module_logger("database").warning(
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
        logger.create_module_logger("database").error(
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
    if not collector.is_healthy():
        collector_issue = "Colector en estado no saludable"
        issues.append(collector_issue)
        critical_issues.append(collector_issue)
        logger.create_module_logger("collectors").error(
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
    if len(sources_config) == 0:
        config_issue = "No hay fuentes configuradas"
        issues.append(config_issue)
        critical_issues.append(config_issue)
        logger.create_module_logger("config").error(
            {
                "event": "config.health.error",
                "trace_id": None,
                "session_id": None,
                "source_id": "config",
                "latency": 0.0,
                "details": {"error": config_issue},
            }
        )

    # Verificar LLM Provider (Ollama)
    _verify_llm_health(logger, warnings)

    return {
        "healthy": len(critical_issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "check_time": datetime.now(timezone.utc).isoformat(),
    }


def _verify_llm_health(  # noqa: C901
    logger: Any,
    warnings: List[str],
    *,
    config: Any | None = None,
) -> None:
    """Internal helper to verify LLM provider availability (Gemini, NVIDIA, or Ollama)."""
    health_logger = _resolve_module_logger(logger, "system")
    if _is_smoke_mode_enabled():
        from news_collector.config import settings as config_settings

        config_settings.set_llm_system_available(False)
        if health_logger:
            health_logger.info(
                "Smoke mode enabled: skipping external LLM health check."
            )
        return

    from news_collector.config import settings as config_settings
    from news_collector.infrastructure.llm.health import resolve_health_checker
    from news_collector.infrastructure.llm.model_registry import (
        is_no_warn_mode_enabled,
        is_strict_mode_enabled,
    )

    active_config = config or config_settings.refresh_runtime_config()
    strict_llm_mode = is_strict_mode_enabled() or is_no_warn_mode_enabled()

    checker = resolve_health_checker(active_config)
    if checker is None:
        return

    try:
        result = checker.check(active_config, health_logger)
    except RuntimeError:
        raise
    except Exception as e:
        if health_logger:
            health_logger.warning(f"LLM health check error: {e}")
        config_settings.set_llm_system_available(False)
        if strict_llm_mode:
            raise RuntimeError(f"LLM health check error: {e}") from e
        return

    if result.warning:
        warnings.append(result.warning)

    if result.disable_llm:
        config_settings.set_llm_system_available(False)
        if result.error and strict_llm_mode:
            raise RuntimeError(result.error)
    else:
        config_settings.set_llm_system_available(True)


def preflight_llm_provider(
    *,
    config: Any | None = None,
    logger: Any = None,
) -> List[str]:
    """Run the current provider health check and return warning messages."""
    warnings: List[str] = []
    _verify_llm_health(logger, warnings, config=config)
    return warnings


def bootstrap_system() -> List[str]:
    """
    Public entrypoint for system bootstrap health checks.
    Returns a list of warning strings. Never raises.
    Specific focus: LLM availability.
    """
    return preflight_llm_provider()
