"""
Bootstrap module for NewsCollectorSystem.
Encapsulates dependency construction and system startup logic.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from news_collector import get_database_manager, get_metrics_reporter, setup_logging
from news_collector.config import ALL_SOURCES, validate_config, validate_sources
from news_collector.validation.validator import ContentValidator


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
            warning_message = f"{db_health['failed_sources']} fuentes fallando"
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


def _verify_llm_health(logger: Any, warnings: List[str]) -> None:
    """Internal helper to verify Ollama availability."""
    try:
        import requests
        from news_collector.config.settings import CONFIG

        ollama_url = CONFIG.ollama.api_url
        # If /api/generate is in the URL, strip it to check base health
        base_url = ollama_url.split("/api/")[0]
        health_url = f"{base_url}/api/tags"  # Standard Ollama check
        
        try:
            resp = requests.get(health_url, timeout=2)
            if resp.status_code != 200:
                warning_msg = f"Ollama health check returned {resp.status_code} at {health_url}"
                warnings.append(warning_msg)
                if logger:
                    logger.create_module_logger("system").warning(warning_msg)
            else:
                 # Check if configured model exists
                 models = resp.json().get("models", [])
                 model_name = CONFIG.ollama.model
                 if not any(m.get("name") == model_name or m.get("model") == model_name for m in models):
                     # Try fuzzy match (e.g. 'llama3.2:latest' vs 'llama3.2')
                     if not any(model_name in (m.get("name") or "") for m in models):
                         warning_msg = f"Model '{model_name}' not found in Ollama. Available: {[m.get('name') for m in models[:3]]}..."
                         warnings.append(warning_msg)
                         if logger:
                             logger.create_module_logger("system").warning(warning_msg)

        except Exception as conn_err:
             warning_msg = f"LLM Provider unreachable at {base_url}: {conn_err}"
             warnings.append(warning_msg)
             # Do not mark as critical to avoid stopping the collector, but log warning
             if logger:
                logger.create_module_logger("system").warning(warning_msg)

    except Exception as e:
        if logger:
            logger.create_module_logger("system").warning(f"Skipping LLM check: {e}")

    # Update global state if LLM issues found
    if any("LLM Provider unreachable" in w for w in warnings) or \
       any("Ollama health check returned" in w for w in warnings):
        import news_collector.config.settings
        news_collector.config.settings.LLM_SYSTEM_AVAILABLE = False
        if logger:
            logger.create_module_logger("system").warning("⚠️ LLM System Disabled due to health check failure.")


def bootstrap_system() -> List[str]:
    """
    Public entrypoint for system bootstrap health checks.
    Returns a list of warning strings. Never raises.
    Specific focus: LLM availability.
    """
    warnings: List[str] = []
    # We pass None as logger to avoid noise/setup complexity during simple CLI checks,
    # or we could set up a basic logger if needed. 
    # For 'surgical' read-only check, None is safer to avoid side effects.
    
    # Run the extracted LLM check
    _verify_llm_health(None, warnings)
    
    return warnings
