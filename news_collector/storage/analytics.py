"""Analytics helpers for database reporting."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from news_collector.storage.models import Article, Source


def collection_stats(
    session: Session, db_type: str, days: int = 30
) -> List[Dict[str, Any]]:
    """Return daily collection stats for the last N days."""
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    date_func = func.date(Article.collected_date)

    stats = (
        session.query(
            date_func.label("collection_date"),
            func.count(Article.id).label("count"),
        )
        .filter(Article.collected_date >= start_date)
        .group_by("collection_date")
        .order_by("collection_date")
        .all()
    )

    return [{"date": str(stat.collection_date), "count": stat.count} for stat in stats]


def source_performance(session: Session) -> List[Dict[str, Any]]:
    """Return average scores and counts per source."""
    results = (
        session.query(
            Article.source_id,
            Source.name.label("source_name"),
            func.count(Article.id).label("article_count"),
            func.avg(Article.final_score).label("avg_score"),
        )
        .join(Source, Article.source_id == Source.id)
        .group_by(Article.source_id, Source.name)
        .order_by(desc("avg_score"))
        .all()
    )

    return [
        {
            "source_id": result.source_id,
            "source_name": result.source_name,
            "article_count": result.article_count,
            "avg_score": float(result.avg_score or 0.0),
        }
        for result in results
    ]


def category_breakdown(session: Session) -> List[Dict[str, Any]]:
    """Return category counts for collected articles."""
    results = (
        session.query(
            Article.category,
            func.count(Article.id).label("count"),
        )
        .group_by(Article.category)
        .order_by(desc("count"))
        .all()
    )
    return [{"category": result.category, "count": result.count} for result in results]


def score_distribution(session: Session, buckets: int = 10) -> Dict[str, int]:
    """Return score histogram buckets for analytics charts."""
    scores = session.query(Article.final_score).filter(Article.final_score > 0).all()
    values = [score[0] for score in scores if score[0] is not None]
    if not values:
        return {}

    distribution = {f"{i / buckets:.1f}": 0 for i in range(buckets)}
    for value in values:
        bucket = min(int(value * buckets), buckets - 1) / buckets
        key = f"{bucket:.1f}"
        distribution[key] = distribution.get(key, 0) + 1
    return distribution


def daily_stats(
    session: Session, date: datetime | date_type | None = None
) -> Dict[str, Any]:
    """Return collection stats for a single day."""
    if date is None:
        day = datetime.now(timezone.utc).date()
    elif isinstance(date, datetime):
        day = date.date()
    else:
        day = date

    start_date = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_date = start_date + timedelta(days=1)

    articles_collected = (
        session.query(func.count(Article.id))
        .filter(Article.collected_date >= start_date)
        .filter(Article.collected_date < end_date)
        .scalar()
    )

    articles_processed = (
        session.query(func.count(Article.id))
        .filter(Article.collected_date >= start_date)
        .filter(Article.collected_date < end_date)
        .filter(Article.processing_status == "completed")
        .scalar()
    )

    avg_score = (
        session.query(func.avg(Article.final_score))
        .filter(Article.collected_date >= start_date)
        .filter(Article.collected_date < end_date)
        .filter(Article.final_score.isnot(None))
        .scalar()
    )

    category_rows = (
        session.query(Article.category, func.count(Article.id))
        .filter(Article.collected_date >= start_date)
        .filter(Article.collected_date < end_date)
        .group_by(Article.category)
        .all()
    )
    category_distribution: Dict[str, int] = {}
    for category, count in category_rows:
        category_distribution[str(category or "unknown")] = int(count)

    collected_count = int(articles_collected or 0)
    processed_count = int(articles_processed or 0)

    return {
        "date": day.isoformat(),
        "articles_collected": collected_count,
        "articles_processed": processed_count,
        "processing_rate": (processed_count / max(collected_count, 1)) * 100,
        "average_score": round(avg_score or 0.0, 3),
        "category_distribution": category_distribution,
    }


def top_sources_performance(
    session: Session, days_back: int = 30
) -> List[Dict[str, Any]]:
    """Return top sources over the given time window."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    article_agg = (
        session.query(
            Article.source_id.label("source_id"),
            func.count(Article.id).label("article_count"),
            func.avg(Article.final_score).label("avg_score"),
            func.max(Article.final_score).label("max_score"),
        )
        .filter(Article.processing_status == "completed")
        .filter(Article.collected_date >= cutoff_date)
        .group_by(Article.source_id)
        .subquery()
    )

    results = (
        session.query(
            Source.id,
            Source.name,
            article_agg.c.article_count,
            article_agg.c.avg_score,
            article_agg.c.max_score,
        )
        .join(article_agg, article_agg.c.source_id == Source.id)
        .order_by(desc(article_agg.c.avg_score))
        .all()
    )

    return [
        {
            "source_id": result.id,
            "source_name": result.name,
            "article_count": result.article_count,
            "average_score": round(result.avg_score or 0.0, 3),
            "max_score": round(result.max_score or 0.0, 3),
        }
        for result in results
    ]
