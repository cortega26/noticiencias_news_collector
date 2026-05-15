"""
Analytics repository — stats, reporting, maintenance, and health queries.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from news_collector.utils.logger import get_logger

from .analytics import (
    category_breakdown,
    collection_stats,
    daily_stats,
    score_distribution,
    source_performance,
    top_sources_performance,
)
from .maintenance import cleanup_old_data, health_status

logger = get_logger().create_module_logger(__name__)


class AnalyticsRepository:
    """
    Focused repository for analytics queries, daily stats, and maintenance.

    Receives a DatabaseManager (or any object with ``get_session()``) as its
    session provider.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    @contextmanager
    def _session(self):
        with self._db.get_session() as session:
            yield session

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_collection_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """Return daily collection stats for the last N days."""
        with self._session() as session:
            return collection_stats(session, self._db.config["type"], days)

    def get_source_performance(self) -> List[Dict[str, Any]]:
        """Return average scores and counts per source."""
        with self._session() as session:
            return source_performance(session)

    def get_category_breakdown(self) -> List[Dict[str, Any]]:
        """Return category distribution of collected articles."""
        with self._session() as session:
            return category_breakdown(session)

    def get_score_distribution(self, buckets: int = 10) -> Dict[str, int]:
        """Return score histogram buckets for analytics charts."""
        with self._session() as session:
            return score_distribution(session, buckets=buckets)

    # ------------------------------------------------------------------
    # Daily / top-source reports
    # ------------------------------------------------------------------

    def get_daily_stats(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """Return collection stats for a single day."""
        with self._session() as session:
            return daily_stats(session, date)

    def get_top_sources_performance(self, days_back: int = 30) -> List[Dict[str, Any]]:
        """Return top sources over the given time window."""
        with self._session() as session:
            return top_sources_performance(session, days_back=days_back)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_old_data(self, days_to_keep: int = 90) -> Dict[str, Any]:
        """Delete stale records and return cleanup metadata."""
        with self._session() as session:
            result = cleanup_old_data(session, days_to_keep)
            logger.info(
                "Cleanup complete: %s articles, %s logs deleted",
                result["deleted_articles"],
                result["deleted_score_logs"],
            )
            return result

    def get_health_status(self) -> Dict[str, Any]:
        """Return database health summary."""
        with self._session() as session:
            return health_status(session, self._db.config["type"])
