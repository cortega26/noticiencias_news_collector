"""
Source repository — circuit breaker state, feed metadata, and initialization.
"""

import contextlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, cast

from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import QueryableAttribute

from news_collector.config.settings import get_runtime_config
from news_collector.utils.logger import get_logger

from .models import Source

logger = get_logger().create_module_logger(__name__)


class SourceRepository:
    """
    Focused repository for source CRUD, circuit breaker state, and feed metadata.

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
    # Circuit breaker
    # ------------------------------------------------------------------

    def get_source_circuit_state(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve circuit breaker state for a source."""
        with self._session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return None
            return {
                "status": source.status,
                "next_retry_at": source.next_retry_at,
                "consecutive_failures": source.consecutive_failures,
                "is_active": source.is_active,
                "last_checked": source.last_checked,
            }

    def update_source_circuit_state(
        self,
        source_id: str,
        success: bool,
        error_message: Optional[str] = None,
        force_cooldown_until: Optional[datetime] = None,
    ) -> None:
        """
        Update circuit breaker state for a source.

        3 consecutive failures → COOLDOWN (configurable hours).
        ``force_cooldown_until`` allows immediate backoff (e.g. for 429s).
        """
        with self._session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return

            if success:
                if source.consecutive_failures > 0 or source.status != "ACTIVE":
                    source.consecutive_failures = 0
                    source.status = "ACTIVE"
                    source.next_retry_at = None
                    source.error_message = None
                    logger.info(
                        "Source {} recovered/healthy. Reset circuit.", source_id
                    )
            else:
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
                source.error_message = (
                    str(error_message)[:500] if error_message else "Unknown Error"
                )

                collection_config = get_runtime_config().collection_config
                max_failures = collection_config.get("circuit_breaker_max_failures", 3)
                cooldown_hours = collection_config.get(
                    "circuit_breaker_cooldown_hours", 4
                )

                if force_cooldown_until:
                    source.status = "COOLDOWN"
                    source.next_retry_at = force_cooldown_until
                    logger.warning(
                        "Circuit breaker forced: source {} entering COOLDOWN until {} (reason: {})",
                        source_id,
                        source.next_retry_at,
                        error_message,
                    )
                elif source.consecutive_failures >= max_failures:
                    source.status = "COOLDOWN"
                    source.next_retry_at = datetime.now(timezone.utc) + timedelta(
                        hours=cooldown_hours
                    )
                    logger.warning(
                        "Circuit breaker tripped: source {} entering COOLDOWN until {}",
                        source_id,
                        source.next_retry_at,
                    )

            session.add(source)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def set_source_active(self, source_id: str, active: bool) -> bool:
        """Enable/disable a source for collection (is_active flag).

        Circuit state (status/cooldown) is left untouched — this only
        gates whether the collector picks the source up in future cycles.
        Returns False when the source row does not exist.
        """
        with self._session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if source is None:
                return False
            source.is_active = active
            session.add(source)
            logger.info("Source {} is_active -> {}", source_id, active)
            return True

    def initialize_sources(self, sources_config: Dict[str, Dict]) -> None:
        """Create or update source records from a config dictionary."""
        with self._session() as session:
            for source_id, source_config in sources_config.items():
                existing = session.query(Source).filter_by(id=source_id).first()

                if existing:
                    existing.name = source_config["name"]
                    existing.url = source_config["url"]
                    existing.credibility_score = source_config["credibility_score"]
                    existing.category = source_config["category"]
                    existing.update_frequency = source_config.get("update_frequency")
                    if source_config.get("etag"):
                        existing.feed_etag = source_config["etag"]
                    if source_config.get("last_modified"):
                        existing.feed_last_modified = source_config["last_modified"]
                    if "blacklisted" in source_config:
                        existing.blacklisted = source_config["blacklisted"]
                    if "blacklist_reason" in source_config:
                        existing.blacklist_reason = source_config["blacklist_reason"]
                    if "blacklisted_date" in source_config:
                        with contextlib.suppress(ValueError, TypeError):
                            existing.blacklisted_at = datetime.fromisoformat(
                                source_config["blacklisted_date"]
                            ).replace(tzinfo=timezone.utc)
                else:
                    new_source = Source(
                        id=source_id,
                        name=source_config["name"],
                        url=source_config["url"],
                        credibility_score=source_config["credibility_score"],
                        category=source_config["category"],
                        update_frequency=source_config.get("update_frequency"),
                        is_active=True,
                        feed_etag=source_config.get("etag"),
                        feed_last_modified=source_config.get("last_modified"),
                    )
                    session.add(new_source)

            logger.info("{} sources initialised/updated", len(sources_config))

    # ------------------------------------------------------------------
    # Feed metadata (ETag / Last-Modified)
    # ------------------------------------------------------------------

    def get_source_feed_metadata(self, source_id: str) -> Dict[str, Optional[str]]:
        """Return cached HTTP headers for a source."""
        with self._session() as session:
            source_etag_attr = cast(QueryableAttribute[Any], Source.feed_etag)
            source_last_modified_attr = cast(
                QueryableAttribute[Any], Source.feed_last_modified
            )
            source = (
                session.query(Source)
                .options(load_only(source_etag_attr, source_last_modified_attr))
                .filter_by(id=source_id)
                .first()
            )
            if not source:
                return {}
            return {
                "etag": source.feed_etag,
                "last_modified": source.feed_last_modified,
            }

    def update_source_feed_metadata(
        self,
        source_id: str,
        *,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """Update cached HTTP headers after a successful feed fetch."""
        if etag is None and last_modified is None and content_hash is None:
            return

        with self._session() as session:
            source = session.query(Source).filter_by(id=source_id).first()
            if not source:
                return
            if etag is not None:
                source.feed_etag = etag
            if last_modified is not None:
                source.feed_last_modified = last_modified
            if content_hash is not None:
                custom_config = dict(source.custom_config or {})
                custom_config["content_hash"] = content_hash
                source.custom_config = custom_config

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def update_source_stats(self, source_id: str, stats: Dict[str, Any]) -> None:
        """Update source statistics after a collection run."""
        with self._session() as session:
            source = session.query(Source).filter_by(id=source_id).first()
            if source:
                source.last_checked = datetime.now(timezone.utc)
                if stats.get("success", False):
                    source.last_successful_check = datetime.now(timezone.utc)
                    if stats.get("articles_found", 0) > 0:
                        source.last_article_found = datetime.now(timezone.utc)
                        source.total_articles_collected += stats["articles_found"]
                    source.consecutive_failures = 0
                else:
                    source.consecutive_failures += 1
                    source.error_message = stats.get("error_message")

                if source.total_articles_collected > 0:
                    success_rate = 1.0 - (
                        source.consecutive_failures
                        / max(source.total_articles_collected, 1)
                    )
                    source.success_rate = max(0.0, success_rate)
