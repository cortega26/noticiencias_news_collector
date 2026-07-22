"""Plan 038 Steps 4-5: unit tests for the pure analytics read model
extracted from `admin_panel.py`'s Tab 4. No Streamlit dependency — this
runs under the main `.venv`, unlike the AppTest-based characterization/
caching tests in `tests_refinery/` (isolated `.venv-refinery`)."""

from __future__ import annotations

from apps.refinery.analytics_read_model import build_analytics_read_model


class _FakeDB:
    def __init__(self, stats, source_perf, dist, cats):
        self._stats = stats
        self._source_perf = source_perf
        self._dist = dist
        self._cats = cats
        self.calls: list = []

    def get_collection_stats(self, days: int = 30):
        self.calls.append(("get_collection_stats", days))
        return self._stats

    def get_source_performance(self):
        self.calls.append(("get_source_performance",))
        return self._source_perf

    def get_score_distribution(self, buckets: int = 10):
        self.calls.append(("get_score_distribution", buckets))
        return self._dist

    def get_category_breakdown(self):
        self.calls.append(("get_category_breakdown",))
        return self._cats


def test_read_model_computes_total_articles_and_avg_score():
    db = _FakeDB(
        stats=[{"date": "2026-01-01", "count": 3}, {"date": "2026-01-02", "count": 2}],
        source_perf=[
            {"source_name": "A", "avg_score": 4.0, "article_count": 3},
            {"source_name": "B", "avg_score": 2.0, "article_count": 2},
        ],
        dist={"0-1": 1, "1-2": 4},
        cats=[{"category": "science", "count": 5}],
    )

    model = build_analytics_read_model(db)

    assert model["total_articles"] == 5
    # (4.0*3 + 2.0*2) / 5 = 3.2
    assert model["avg_score_overall"] == 3.2
    assert model["dist"] == {"0-1": 1, "1-2": 4}
    assert model["cats"] == [{"category": "science", "count": 5}]
    assert model["stats"] == db._stats
    assert model["source_perf"] == db._source_perf


def test_read_model_top_sources_sorted_desc_capped_at_five():
    source_perf = [
        {"source_name": f"S{i}", "avg_score": float(i), "article_count": 1}
        for i in range(8)
    ]
    db = _FakeDB(stats=[], source_perf=source_perf, dist={}, cats=[])

    model = build_analytics_read_model(db)

    assert [s["source_name"] for s in model["top_sources"]] == [
        "S7",
        "S6",
        "S5",
        "S4",
        "S3",
    ]


def test_read_model_handles_zero_articles_without_division_error():
    db = _FakeDB(stats=[], source_perf=[], dist={}, cats=[])

    model = build_analytics_read_model(db)

    assert model["total_articles"] == 0
    assert model["avg_score_overall"] == 0
    assert model["top_sources"] == []


def test_read_model_calls_every_query_exactly_once():
    db = _FakeDB(stats=[{"date": "d", "count": 1}], source_perf=[], dist={}, cats=[])

    build_analytics_read_model(db)

    method_names = [c[0] for c in db.calls]
    assert method_names.count("get_collection_stats") == 1
    assert method_names.count("get_source_performance") == 1
    assert method_names.count("get_score_distribution") == 1
    assert method_names.count("get_category_breakdown") == 1
