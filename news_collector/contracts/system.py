"""
Contratos explícitos para la configuración y control del sistema.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SystemConfigOverrideModel(BaseModel):
    """
    Define un contrato estricto para las anulaciones (overrides) de configuración
    que se pasan durante la inicialización de NewsCollectorSystem.
    Previene errores en runtime debido a inyecciones de datos malformados.
    """
    model_config = ConfigDict(extra="ignore")

    scoring_workers: Optional[int] = Field(
        default=None,
        ge=1, le=16,
        description="Override for max parallel scoring workers"
    )

    # Permite inyecciones controladas a capas submódulos
    dispatcher_enabled: Optional[bool] = Field(default=None)
