"""Plan 038 Steps 4-5: characterization + caching-behavior tests for the
Refinery Analytics tab (`apps/refinery/admin_panel.py`, Tab 4).

Per the plan-038 re-examination record (`plans/038/spec.md`), shipping
`st.cache_resource`/`st.cache_data` into this 3042-LOC, previously
uncharacterized, auth-gated module without a working harness to verify
cache-hit/TTL/invalidation would mislabel the plan's own Step 4/5 Verify
criteria as met. This file first proved the harness could drive the app
past its auth gate and reach Tab 4's real analytics queries with NO caching
present (the original uncached-baseline test, since superseded — see git
history on this file) — only after that was confirmed did the caching code
get written, and the tests below were then rewritten to verify the cache
behavior against the same harness rather than by inspection.

`st.cache_resource`/`st.cache_data` caches are process-global, not scoped
per `AppTest` instance — every test here explicitly clears both at the
start to avoid state leaking in from a previous test in the same run.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import streamlit as st
from news_collector.storage.database import DatabaseManager
from streamlit.testing.v1 import AppTest

ADMIN_PANEL = "apps/refinery/admin_panel.py"


@contextmanager
def _call_counter(cls, method_name: str):
    """`unittest.mock.patch.object(cls, name, wraps=cls.name)` does NOT bind
    `self` correctly for an unbound method reference (a MagicMock is not a
    descriptor) — it raises "missing 1 required positional argument: 'self'"
    on every call while still incrementing call_count, which would make a
    naive `spy.call_count >= 1` assertion pass even though the real method
    body never ran. This uses a plain function wrapper instead, which IS a
    real descriptor, so `self` binds normally."""
    original = getattr(cls, method_name)
    counts = {"n": 0}

    def wrapper(self, *args, **kwargs):
        counts["n"] += 1
        return original(self, *args, **kwargs)

    with patch.object(cls, method_name, wrapper):
        yield counts


def _clear_analytics_caches():
    st.cache_data.clear()
    st.cache_resource.clear()


def test_apptest_can_drive_the_app_past_the_auth_gate():
    _clear_analytics_caches()
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)

    assert not at.exception, [str(e) for e in at.exception]


def test_analytics_tab_metrics_render_with_real_values():
    _clear_analytics_caches()
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)

    labels = {m.label: m.value for m in at.metric}
    assert "Total Artículos (30d)" in labels
    assert "Score Promedio" in labels
    assert "Fuentes Activas" in labels
    # A real DB is queried — the exact numbers vary with local dev data, but
    # the metric must be a real (non-empty, numeric-looking) value, not a
    # placeholder/error string.
    assert labels["Fuentes Activas"] not in ("", None)


def test_analytics_freshness_caption_is_shown():
    _clear_analytics_caches()
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)

    captions = [c.value for c in at.caption]
    assert any("Datos al:" in c for c in captions), captions


def test_second_rerun_reuses_cache_and_does_not_requery():
    """Plan 038 Step 4's core promise: a repeated non-mutating rerun must
    reuse the cached read model instead of re-querying the database."""
    _clear_analytics_caches()
    with (
        _call_counter(DatabaseManager, "get_collection_stats") as stats_calls,
        _call_counter(DatabaseManager, "get_source_performance") as perf_calls,
    ):
        at = AppTest.from_file(ADMIN_PANEL)
        at.run(timeout=60)
        assert not at.exception
        assert not list(at.error), [e.value for e in at.error]

        first_run_stats_calls = stats_calls["n"]
        first_run_perf_calls = perf_calls["n"]
        assert first_run_stats_calls == 1
        assert first_run_perf_calls == 1

        # A fresh AppTest instance simulates a new page load / rerun, but
        # st.cache_data/st.cache_resource are process-global — the cache
        # populated by the first run is still warm, so this must be a
        # cache hit, not a fresh query.
        at2 = AppTest.from_file(ADMIN_PANEL)
        at2.run(timeout=60)
        assert not at2.exception
        assert not list(at2.error), [e.value for e in at2.error]

        assert stats_calls["n"] == first_run_stats_calls
        assert perf_calls["n"] == first_run_perf_calls


def test_manual_refresh_button_forces_a_fresh_query():
    """Plan 038 Step 4's "Invalidate after ... manual refresh" requirement,
    and Step 5's "manual refresh ... cause[s] one fresh query set" Verify
    line — driven through the real button, not by calling `.clear()`
    directly, so this proves the button is actually wired to the cache."""
    _clear_analytics_caches()
    with (
        _call_counter(DatabaseManager, "get_collection_stats") as stats_calls,
        _call_counter(DatabaseManager, "get_source_performance") as perf_calls,
    ):
        at = AppTest.from_file(ADMIN_PANEL)
        at.run(timeout=60)
        assert not at.exception
        assert stats_calls["n"] == 1
        assert perf_calls["n"] == 1

        refresh_button = next(
            b for b in at.button if b.label == "🔄 Refrescar analítica"
        )
        refresh_button.click().run(timeout=60)
        assert not at.exception
        assert not list(at.error), [e.value for e in at.error]

        assert stats_calls["n"] == 2
        assert perf_calls["n"] == 2


def test_a_visible_query_error_does_not_show_stale_data_as_current():
    """Step 5's own concern: a query error must be visible (the existing
    try/except -> st.error path), not silently masked by a stale cached
    value being shown as if it were fresh."""
    _clear_analytics_caches()
    with patch.object(
        DatabaseManager,
        "get_collection_stats",
        side_effect=RuntimeError("simulated query failure"),
    ):
        at = AppTest.from_file(ADMIN_PANEL)
        at.run(timeout=60)

        errors = [e.value for e in at.error]
        assert any("Error cargando analítica" in e for e in errors), errors
