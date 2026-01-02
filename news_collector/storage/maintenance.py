"""Maintenance helpers for database cleanup and health checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from news_collector.storage.models import Article, PENDING_STATUS, ScoreLog, Source


def cleanup_old_data(session: Session, days_to_keep: int = 90) -> Dict[str, Any]:
    """Delete stale records and return cleanup metadata."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

    deleted_articles = (
        session.query(Article)
        .filter(Article.collected_date < cutoff_date)
        .filter(Article.final_score < 0.3)
        .delete()
    )

    deleted_logs = (
        session.query(ScoreLog)
        .filter(ScoreLog.calculated_at < cutoff_date)
        .delete()
    )

    return {
        "deleted_articles": deleted_articles,
        "deleted_score_logs": deleted_logs,
        "cutoff_date": cutoff_date.isoformat(),
    }


def health_status(session: Session, db_type: str) -> Dict[str, Any]:
    """Return database health summary."""
    total_articles = session.query(func.count(Article.id)).scalar()
    pending_articles = (
        session.query(func.count(Article.id))
        .filter(Article.processing_status == PENDING_STATUS)
        .scalar()
    )

    recent_articles = (
        session.query(func.count(Article.id))
        .filter(
            Article.collected_date >= datetime.now(timezone.utc) - timedelta(days=1)
        )
        .scalar()
    )

    active_sources = (
        session.query(func.count(Source.id))
        .filter(Source.is_active.is_(True))
        .scalar()
    )

    failed_sources = (
        session.query(func.count(Source.id))
        .filter(Source.consecutive_failures > 3)
        .scalar()
    )

    return {
        "total_articles": total_articles,
        "pending_processing": pending_articles,
        "articles_last_24h": recent_articles,
        "active_sources": active_sources,
        "failed_sources": failed_sources,
        "database_type": db_type,
        "status": (
            "healthy"
            if failed_sources == 0 and pending_articles < 100
            else "warning"
        ),
    }
