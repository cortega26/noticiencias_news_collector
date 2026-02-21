# src/exceptions.py
# Taxonomía unificada de errores para News Collector System
# ========================================================
"""
Define la jerarquía de excepciones y códigos de salida para el sistema.
Garantiza que todos los errores se mapeen a categorías consistentes y accionables.
"""

from typing import Optional

# Exit Codes Taxonomy
# -------------------
EXIT_SUCCESS = 0
EXIT_USER_INPUT = 2  # Error de entrada de usuario (argumentos inválidos)
EXIT_CONFIG = 3  # Error de configuración (archivo inválido, faltan claves)
EXIT_INGESTION = 4  # Error de ingestion (fuente caída, parsing fallido)
EXIT_CONTRACT = 5  # Error de contrato interno (validación fallida)
EXIT_OPERATIONAL = 6  # Error operacional I/O (base de datos, disco lleno, red)
EXIT_INTERNAL = 10  # Error interno inesperado (bug, lógica rota)


class NewsCollectorError(Exception):
    """
    Excepción base para todos los errores controlados del sistema.
    """

    exit_code = EXIT_INTERNAL
    category = "GENERIC_ERROR"

    def __init__(self, message: str, original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.original_exception = original_exception


# Category: Configuration (3)
# ---------------------------
class ConfigError(NewsCollectorError):
    """Errores en carga o validación de configuración."""

    exit_code = EXIT_CONFIG
    category = "CONFIGURATION_ERROR"


# Category: Ingestion (4)
# -----------------------
class IngestionError(NewsCollectorError):
    """Errores generales durante la fase de recolección."""

    exit_code = EXIT_INGESTION
    category = "INGESTION_ERROR"


class SourceUnavailableError(IngestionError):
    """La fuente no es accesible (red, 404, timeout)."""

    category = "SOURCE_UNAVAILABLE"


class LLMInvocationError(IngestionError):
    """Error al invocar servicios de LLM (traducción/resumen)."""

    category = "LLM_ERROR"


# Category: Contract (5)
# ----------------------
class ContractError(NewsCollectorError):
    """Violación de contratos de datos internos."""

    exit_code = EXIT_CONTRACT
    category = "CONTRACT_ERROR"


class ContractValidationError(ContractError):
    """Fallo en validación de Pydantic o reglas de negocio."""

    category = "VALIDATION_ERROR"


# Category: Operational (6)
# -------------------------
class OperationalError(NewsCollectorError):
    """Errores de infraestructura o I/O (DB, FileSystem)."""

    exit_code = EXIT_OPERATIONAL
    category = "OPERATIONAL_ERROR"


class OperationalIOError(OperationalError):
    """Error específico de I/O (disco, permisos)."""

    category = "IO_ERROR"


# Category: Internal / Logic (10)
# -------------------------------
class ScoringError(NewsCollectorError):
    """Error durante el cálculo de puntajes."""

    exit_code = EXIT_INTERNAL
    category = "SCORING_ERROR"


class PublishingError(NewsCollectorError):
    """Error durante la publicación final (GitHub PR)."""

    exit_code = EXIT_INTERNAL
    category = "PUBLISHING_ERROR"
