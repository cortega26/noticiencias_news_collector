# src/utils/logger.py
# Sistema de logging avanzado para News Collector
# ==============================================

"""
Este módulo configura un sistema de logging robusto y elegante para nuestro
News Collector. Es como tener un sistema de monitoreo inteligente que observa
cada evento que sucede en nuestro sistema, registra información importante, y
nos alerta cuando algo requiere atención.

Usamos loguru porque es mucho más elegante y potente que el logging estándar
de Python, proporcionando formato automático bonito, rotación de archivos,
y filtrado inteligente.
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from news_collector.config.settings import DEBUG, LOGGING_CONFIG
from loguru import logger


class NewsCollectorLogger:
    """
    Configurador centralizado de logging para el sistema completo.

    Esta clase es como el director de un sistema de comunicaciones
    que asegura que cada dato importante se registre
    de manera consistente y útil en toda la plataforma.
    """

    def __init__(self):
        self.is_configured = False
        self.log_file_path: Optional[Path] = None

    def configure_logging(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Configura el sistema de logging según la configuración proporcionada.

        Esta función establece todos los handlers, formatos, y filtros
        necesarios para tener un sistema de logging profesional.

        Args:
            config: Configuración de logging. Si no se proporciona,
                   usa la configuración por defecto de settings.py
        """
        if self.is_configured:
            logger.info("Logger ya configurado, omitiendo reconfiguración")
            return

        config = config or LOGGING_CONFIG

        # Override level from environment variable to support runtime changes (e.g. CLI args)
        import os
        env_level = os.environ.get("LOG_LEVEL")
        if env_level:
            # Create a copy to avoid mutating the global configuration
            config = config.copy()
            config["level"] = env_level

        # Remover configuración por defecto de loguru
        logger.remove()

        # Configurar handler para consola (siempre activo)
        self._configure_console_handler(config)

        # Configurar handler para archivo (si está especificado)
        if config.get("file_path"):
            self._configure_file_handler(config)

        # Configurar filtros especiales para desarrollo/producción
        self._configure_filters(config)

        # Marcar como configurado
        self.is_configured = True

        logger.info("🎯 Sistema de logging configurado exitosamente")
        logger.debug(f"Configuración aplicada: {config}")

    def log_system_health(self) -> None:
        """Expone el log de salud del sistema desde la instancia."""
        _log_system_health()

    def _configure_console_handler(self, config: Dict[str, Any]) -> None:
        """
        Configura el handler para output de consola.

        En desarrollo mostramos logs coloridos y detallados.
        En producción mostramos logs más compactos y profesionales.
        """
        
        def console_filter(record):
            """Filtra logs estructurados (JSON) de nivel INFO para evitar spam en consola."""
            msg = str(record["message"]).strip()
            # Si parece un log estructurado (empieza con llaves y tiene 'event')
            if (msg.startswith("{'event'") or msg.startswith('{"event"')):
                # Permitir solo si es WARNING o ERROR, ocultar INFO/DEBUG
                if record["level"].no >= 30: # WARNING=30
                    return True
                return False
            return True

        if DEBUG:
            # Formato desarrollo: colorido y con detalles completos
            console_format = (
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
            console_level = "DEBUG"
        else:
            # Formato producción: más limpio y profesional (sin fecha, solo hora)
            console_format = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"
            console_level = config.get("level", "INFO")

        logger.add(
            sys.stdout,
            format=console_format,
            level=console_level,
            colorize=True,
            filter=console_filter, # Aplicar filtro anti-spam
            backtrace=DEBUG,  # Stack traces detallados solo en desarrollo
            diagnose=DEBUG,  # Variables locales solo en desarrollo
        )

    def _configure_file_handler(self, config: Dict[str, Any]) -> None:
        """
        Configura el handler para logging a archivo.

        Incluye rotación automática, retención configurable,
        y formato optimizado para análisis posterior.
        """
        self.log_file_path = Path(config["file_path"])

        # Crear directorio si no existe
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Formato para archivo: structured y parseable
        file_format = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{process.id: <6} | "
            "{name}:{function}:{line} | "
            "{message}"
        )

        logger.add(
            str(self.log_file_path),
            format=file_format,
            level=config.get("level", "INFO"),
            rotation=config.get("max_file_size", "10 MB"),
            retention=config.get("retention", "30 days"),
            compression="gz",  # Comprimir logs antiguos
            enqueue=True,  # Threading seguro
            serialize=True, # SRE Requirement: Structured JSON logs
            backtrace=True,  # Stack traces completos en archivo
            diagnose=True,  # Variables locales en archivo
        )

    def _configure_filters(self, config: Dict[str, Any]) -> None:
        """
        Configura filtros especiales para diferentes tipos de logs.

        Esto nos permite tener control granular sobre qué se registra
        y cómo se formatea según el contexto.
        """

        # Filtro para requests HTTP (para evitar spam de requests)
        def filter_http_requests(record):
            # Reducir verbosidad de requests exitosos
            if "requests" in record["name"] and record["level"].name == "DEBUG":
                return False
            return True

        # Filtro para base de datos (para evitar spam de SQL)
        def filter_db_queries(record):
            # Mostrar solo queries importantes, no todas
            if "sqlalchemy" in record["name"] and record["level"].name == "INFO":
                return False
            return True

        # Aplicar filtros solo si no estamos en modo debug completo
        if not DEBUG:
            logger.add(
                lambda _: None,  # Sink auxiliar para aplicar filtros globalmente
                filter=lambda record: filter_http_requests(record)
                and filter_db_queries(record),
            )

    def create_module_logger(self, module_name: str) -> Any:
        """
        Crea un logger específico para un módulo.

        Esto permite tener logs identificados por módulo, facilitando
        el debugging y análisis de problemas específicos.

        Args:
            module_name: Nombre del módulo (ej: 'collectors.rss')

        Returns:
            Logger configurado para el módulo específico
        """
        # Asegurar que el logging esté configurado
        if not self.is_configured:
            self.configure_logging()

        # Retornar logger con contexto del módulo
        return logger.bind(module=module_name)

    def log_system_startup(
        self,
        version: str = "1.0",
        config_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Registra información de inicio del sistema.

        Esta función crea un log especial que marca el inicio de una sesión
        del sistema, útil para debugging y auditoría.
        """
        logger.info("=" * 60)
        logger.info("🚀 NEWS COLLECTOR SYSTEM INICIADO")
        logger.info("=" * 60)
        logger.info(f"Versión: {version}")
        logger.info(f"Modo debug: {DEBUG}")

        if config_summary:
            logger.info("Configuración principal:")
            for key, value in config_summary.items():
                logger.info(f"  {key}: {value}")

        if self.log_file_path:
            logger.info(f"Logs guardándose en: {self.log_file_path}")

        logger.info("=" * 60)

    def log_performance_metrics(self, metrics: Dict[str, Any], context: str = ""):
        """
        Registra métricas de performance de manera estructurada.

        Esto es útil para monitoreo y optimización del sistema.
        """
        logger.info(f"📊 MÉTRICAS DE PERFORMANCE {context}")
        for metric, value in metrics.items():
            if isinstance(value, float):
                logger.info(f"  {metric}: {value:.3f}")
            else:
                logger.info(f"  {metric}: {value}")

    def log_error_with_context(
        self, error: Exception, context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Registra errores con contexto adicional para facilitar debugging.

        Esta función enriquece los logs de error con información que
        puede ser crucial para entender y resolver problemas.
        """
        logger.error(f"💥 ERROR: {str(error)}")

        if context:
            logger.error("Contexto del error:")
            for key, value in context.items():
                logger.error(f"  {key}: {value}")

        # Log completo del stack trace
        logger.exception("Stack trace completo:")


class CollectionSessionLogger:
    """
    Logger especializado para sesiones de recolección.

    Esta clase proporciona logging estructurado específicamente
    para las sesiones de recolección de noticias, facilitando
    el seguimiento del progreso y análisis de resultados.
    """

    def __init__(self, session_id: str, collector_type: str):
        self.session_id = session_id
        self.collector_type = collector_type
        self.logger = logger.bind(session_id=session_id, collector_type=collector_type)

    def log_session_start(self, sources_count: int):
        """Registra el inicio de una sesión de recolección."""
        self.logger.info(f"🎯 SESIÓN INICIADA: {sources_count} fuentes programadas")

    def log_source_processing(
        self,
        source_id: str,
        status: str,
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registra el procesamiento de una fuente específica."""
        if status == "success":
            articles_info = (
                f"{stats.get('articles_saved', 0)}/{stats.get('articles_found', 0)} artículos"
                if stats
                else ""
            )
            self.logger.info(f"✅ {source_id}: {articles_info}")
        elif status == "error":
            error_msg = (
                stats.get("error_message", "Error desconocido")
                if stats
                else "Error desconocido"
            )
            self.logger.warning(f"❌ {source_id}: {error_msg}")
        else:
            self.logger.info(f"📋 {source_id}: {status}")

    def log_session_summary(self, summary: Dict[str, Any]):
        """Registra el resumen final de la sesión."""
        self.logger.info("📈 RESUMEN DE SESIÓN:")
        self.logger.info(
            f"  • Fuentes procesadas: {summary.get('sources_processed', 0)}"
        )
        self.logger.info(
            f"  • Artículos encontrados: {summary.get('articles_found', 0)}"
        )
        self.logger.info(f"  • Artículos guardados: {summary.get('articles_saved', 0)}")
        self.logger.info(f"  • Tiempo total: {summary.get('duration_seconds', 0):.1f}s")
        self.logger.info(f"  • Tasa de éxito: {summary.get('success_rate', 0):.1f}%")


# Instancia global del configurador de logging
# ============================================
_logger_instance: Optional[NewsCollectorLogger] = None


def get_logger() -> NewsCollectorLogger:
    """
    Función factory para obtener la instancia del logger configurado.

    Implementa el patrón Singleton para asegurar configuración consistente
    en toda la plataforma.
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = NewsCollectorLogger()
        _logger_instance.configure_logging()
    return _logger_instance


def setup_logging(config: Optional[Dict[str, Any]] = None) -> NewsCollectorLogger:
    """
    Función de conveniencia para configurar logging al inicio del sistema.

    Args:
        config: Configuración opcional de logging

    Returns:
        Instancia configurada del logger
    """
    logger_instance = get_logger()
    if config:
        logger_instance.configure_logging(config)
    return logger_instance


# Decorador para logging automático de funciones
# ==============================================


def log_function_calls(logger_instance=None):
    """
    Decorador que automáticamente registra calls a funciones.

    Útil para debugging y monitoreo de performance de funciones críticas.
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            func_logger = logger_instance or logger

            # Log entrada a la función
            func_logger.debug(f"🔄 Ejecutando {func.__name__}")

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                # Log éxito
                func_logger.debug(f"✅ {func.__name__} completada en {duration:.3f}s")
                return result

            except Exception as e:
                duration = time.time() - start_time

                # Log error
                func_logger.error(
                    f"❌ {func.__name__} falló después de {duration:.3f}s: {str(e)}"
                )
                raise

        return wrapper

    return decorator


# Funciones de utilidad para logging común
# =======================================


def log_memory_usage():
    """
    Registra el uso actual de memoria del sistema.
    Útil para monitoreo de performance y detección de memory leaks.
    """
    try:
        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()

        logger.info("💾 Uso de memoria:")
        logger.info(f"  • RSS: {memory_info.rss / 1024 / 1024:.1f} MB")
        logger.info(f"  • VMS: {memory_info.vms / 1024 / 1024:.1f} MB")

    except ImportError:
        logger.debug("psutil no disponible, omitiendo log de memoria")
    except Exception as e:
        logger.warning(f"Error obteniendo info de memoria: {e}")


def _log_system_health():
    """
    Registra información general de salud del sistema.
    """
    try:
        import platform
        import sys

        logger.info("🏥 ESTADO DEL SISTEMA:")
        logger.info(f"  • Python: {sys.version.split()[0]}")
        logger.info(f"  • Plataforma: {platform.platform()}")
        logger.info(f"  • CPU cores: {platform.processor()}")

        log_memory_usage()

    except Exception as e:
        logger.warning(f"Error obteniendo info del sistema: {e}")


# ¿Por qué este sistema de logging?
# =================================
#
# 1. ELEGANCIA: loguru es mucho más limpio y potente que logging estándar
#
# 2. ESTRUCTURADO: Logs organizados por contexto (sesión, módulo, etc.)
#    facilitando análisis posterior
#
# 3. FLEXIBLE: Diferentes niveles y formatos para desarrollo vs producción
#
# 4. PERFORMANTE: Configuración eficiente que no impacta performance
#
# 5. OBSERVABLE: Información rica para debugging y monitoreo
#
# 6. MANTENIBLE: Sistema centralizado fácil de modificar y extender
#
# Este sistema de logging es como tener un sistema nervioso completo
# para nuestro News Collector: nos dice exactamente qué está pasando
# en cada momento y nos ayuda a diagnosticar problemas rápidamente.
