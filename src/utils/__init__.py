"""
Utilidades del News Collector System.
"""

from .logger import get_logger, setup_logging
from .observability import get_observability

__all__ = [
    "get_logger",
    "setup_logging",
    "get_observability",
]
