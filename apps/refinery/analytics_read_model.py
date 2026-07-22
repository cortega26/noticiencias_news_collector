"""Plan 038 Steps 4-5: pure, Streamlit-independent analytics read model.

Extracted verbatim from the Tab 4 (Analytics) block in `admin_panel.py` so
its query composition can be cached (`st.cache_data`) and unit-tested
without a Streamlit runtime. This module must not import `streamlit` or any
`st.*` call — that boundary is what makes it independently testable under
the main `.venv` (which has no `streamlit` installed at all).
"""

from __future__ import annotations

from typing import Any, Dict, Protocol


class _AnalyticsSource(Protocol):
    def get_collection_stats(self, days: int = 30) -> list: ...
    def get_source_performance(self) -> list: ...
    def get_score_distribution(self, buckets: int = 10) -> dict: ...
    def get_category_breakdown(self) -> list: ...


def build_analytics_read_model(db: _AnalyticsSource) -> Dict[str, Any]:
    """Run the exact same 4 queries + derived values Tab 4 always has, and
    return them as a plain dict. Behavior-preserving extraction: no new
    logic, no changed query arguments, no changed derivation formulas."""
    stats = db.get_collection_stats(days=30)
    total_articles = sum(d["count"] for d in stats)

    source_perf = db.get_source_performance()
    avg_score_overall = (
        sum(s["avg_score"] * s["article_count"] for s in source_perf) / total_articles
        if total_articles
        else 0
    )

    dist = db.get_score_distribution()
    cats = db.get_category_breakdown()

    top_sources = (
        sorted(source_perf, key=lambda x: x["avg_score"], reverse=True)[:5]
        if source_perf
        else []
    )

    return {
        "stats": stats,
        "total_articles": total_articles,
        "source_perf": source_perf,
        "avg_score_overall": avg_score_overall,
        "dist": dist,
        "cats": cats,
        "top_sources": top_sources,
    }
