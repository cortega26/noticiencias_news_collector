from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from news_collector.collectors.base_collector import create_collector
from news_collector.collectors.dispatcher import CollectorDispatcher


def test_factory_get_collector():
    with patch("news_collector.collectors.rss_collector.RSSCollector") as mock_rss:
        c = create_collector("rss")
        assert c is not None
        mock_rss.assert_called()


def test_factory_invalid_type():
    with pytest.raises(ValueError, match="no soportado"):
        create_collector("unknown_type")


def test_dispatcher_collect_all():
    dispatcher = CollectorDispatcher()
    with patch.object(
        dispatcher, "collect_from_multiple_sources_async", new_callable=AsyncMock
    ) as mock_async:
        mock_async.return_value = {"summary": "done"}
        res = dispatcher.collect_from_multiple_sources({})
        assert res["summary"] == "done"


def _assert_total_invariant(summary):
    """Plan 040 Step 3: every requested source is succeeded XOR failed,
    exactly once, and the rate is always present and in range."""
    assert (
        summary["sources_succeeded"] + summary["sources_failed"]
        == summary["sources_requested"]
    )
    assert summary["sources_processed"] == summary["sources_requested"]
    assert 0.0 <= summary["success_rate_percent"] <= 100.0


@pytest.mark.asyncio
async def test_dispatcher_failed_task_attributed_with_source_identity():
    """Failed collector tasks must report source IDs and increment counts."""
    dispatcher = CollectorDispatcher()

    mock_collector = MagicMock()
    mock_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("connection refused")
    )
    dispatcher.collectors["rss"] = mock_collector

    sources = {
        "source_a": {"collector_type": "rss"},
        "source_b": {"collector_type": "rss"},
    }

    result = await dispatcher.collect_from_multiple_sources_async(sources)
    summary = result["collection_summary"]

    assert summary["errors_encountered"] == 2
    assert summary["sources_processed"] == 2
    assert summary["sources_failed"] == 2
    assert summary["sources_succeeded"] == 0
    assert "source_a" in result["source_details"]
    assert "source_b" in result["source_details"]
    assert result["source_details"]["source_a"]["success"] is False
    assert result["source_details"]["source_a"]["reason"] == "dispatcher_task_exception"
    assert result["source_details"]["source_a"]["error_class"] == "RuntimeError"
    assert "connection refused" in result["source_details"]["source_a"]["error_message"]
    _assert_total_invariant(summary)


@pytest.mark.asyncio
async def test_dispatcher_partial_failure_mixed_results():
    """One failing and one succeeding task must both be counted."""
    dispatcher = CollectorDispatcher()

    fail_collector = MagicMock()
    fail_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("timeout")
    )
    success_collector = MagicMock()
    success_collector.collect_from_multiple_sources_async = AsyncMock(
        return_value={
            "source_details": {"good_source": {"success": True}},
            "collection_summary": {
                "sources_processed": 1,
                "articles_found": 3,
                "articles_saved": 3,
                "errors_encountered": 0,
            },
        }
    )
    dispatcher.collectors["rss"] = fail_collector
    dispatcher.collectors["html"] = success_collector

    sources = {
        "bad_source": {"collector_type": "rss"},
        "good_source": {"collector_type": "html"},
    }

    result = await dispatcher.collect_from_multiple_sources_async(sources)
    summary = result["collection_summary"]

    assert summary["errors_encountered"] == 1
    assert summary["sources_processed"] == 2
    assert summary["sources_succeeded"] == 1
    assert summary["sources_failed"] == 1
    assert result["source_details"]["bad_source"]["success"] is False

    assert result["source_details"]["good_source"]["success"] is True
    assert summary["articles_found"] == 3
    _assert_total_invariant(summary)


@pytest.mark.asyncio
async def test_dispatcher_all_success_via_real_merge_path():
    """All-success case exercised through the real gather/merge logic,
    not mocked away (unlike test_dispatcher_collect_all)."""
    dispatcher = CollectorDispatcher()

    rss_collector = MagicMock()
    rss_collector.collect_from_multiple_sources_async = AsyncMock(
        return_value={
            "source_details": {
                "s1": {"success": True},
                "s2": {"success": True},
            },
            "collection_summary": {
                "sources_processed": 2,
                "articles_found": 5,
                "articles_saved": 4,
                "errors_encountered": 0,
            },
        }
    )
    dispatcher.collectors["rss"] = rss_collector

    sources = {
        "s1": {"collector_type": "rss"},
        "s2": {"collector_type": "rss"},
    }
    result = await dispatcher.collect_from_multiple_sources_async(sources)
    summary = result["collection_summary"]

    assert summary["sources_requested"] == 2
    assert summary["sources_succeeded"] == 2
    assert summary["sources_failed"] == 0
    assert summary["success_rate_percent"] == 100.0
    assert summary["articles_found"] == 5
    assert summary["articles_saved"] == 4
    _assert_total_invariant(summary)


@pytest.mark.asyncio
async def test_dispatcher_malformed_result_attributed_as_failure():
    """A child collector returning a non-dict, non-exception value must
    not silently vanish — it becomes a counted failure per source."""
    dispatcher = CollectorDispatcher()

    malformed_collector = MagicMock()
    malformed_collector.collect_from_multiple_sources_async = AsyncMock(
        return_value=None
    )
    dispatcher.collectors["rss"] = malformed_collector

    sources = {
        "m1": {"collector_type": "rss"},
        "m2": {"collector_type": "rss"},
    }
    result = await dispatcher.collect_from_multiple_sources_async(sources)
    summary = result["collection_summary"]

    assert result["source_details"]["m1"]["success"] is False
    assert result["source_details"]["m1"]["reason"] == "malformed_result"
    assert summary["sources_failed"] == 2
    _assert_total_invariant(summary)


@pytest.mark.asyncio
async def test_dispatcher_missing_collector_attributed_as_failure():
    """If even the rss fallback target has no registered collector
    (e.g. total initialization failure), requested sources must be
    counted as failures, not silently dropped."""
    dispatcher = CollectorDispatcher()
    dispatcher.collectors.clear()  # simulate every collector failing init

    sources = {
        "orphan_a": {"collector_type": "rss"},
        "orphan_b": {"collector_type": "html"},
    }
    result = await dispatcher.collect_from_multiple_sources_async(sources)
    summary = result["collection_summary"]

    assert result["source_details"]["orphan_a"]["success"] is False
    assert result["source_details"]["orphan_a"]["reason"] == "collector_unavailable"
    assert result["source_details"]["orphan_b"]["reason"] == "collector_unavailable"
    assert summary["sources_requested"] == 2
    assert summary["sources_failed"] == 2
    _assert_total_invariant(summary)


@pytest.mark.asyncio
async def test_dispatcher_unknown_collector_type_falls_back_to_rss():
    """Deliberate, kept behavior (plan 040 STOP-condition decision): an
    unrecognized `collector_type` in a source's own config silently
    coerces to 'rss' rather than being rejected — not externally
    promised anywhere else, but not changed by this plan either. This
    test locks it in so it is no longer untested."""
    dispatcher = CollectorDispatcher()

    rss_collector = MagicMock()
    rss_collector.collect_from_multiple_sources_async = AsyncMock(
        return_value={
            "source_details": {"weird": {"success": True}},
            "collection_summary": {
                "sources_processed": 1,
                "articles_found": 1,
                "articles_saved": 1,
                "errors_encountered": 0,
            },
        }
    )
    dispatcher.collectors["rss"] = rss_collector

    sources = {"weird": {"collector_type": "totally_made_up_type"}}
    result = await dispatcher.collect_from_multiple_sources_async(sources)

    rss_collector.collect_from_multiple_sources_async.assert_awaited_once()
    called_sources = rss_collector.collect_from_multiple_sources_async.call_args[0][0]
    assert "weird" in called_sources
    assert result["source_details"]["weird"]["success"] is True


@pytest.mark.asyncio
async def test_dispatcher_empty_input_returns_zeroed_totals():
    dispatcher = CollectorDispatcher()
    result = await dispatcher.collect_from_multiple_sources_async({})
    summary = result["collection_summary"]

    assert summary["sources_requested"] == 0
    assert summary["sources_processed"] == 0
    assert summary["sources_succeeded"] == 0
    assert summary["sources_failed"] == 0
    assert summary["success_rate_percent"] == 0.0
    assert result["source_details"] == {}


@pytest.mark.asyncio
async def test_dispatcher_reports_failures_to_health_tracker():
    tracker = MagicMock()
    dispatcher = CollectorDispatcher(health_tracker=tracker)

    fail_collector = MagicMock()
    fail_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    dispatcher.collectors["rss"] = fail_collector

    await dispatcher.collect_from_multiple_sources_async(
        {"s1": {"collector_type": "rss"}}
    )

    tracker.record_attempt.assert_any_call("s1")
    tracker.record_failure.assert_any_call(
        "s1",
        "unknown",
        "dispatcher_task_exception",
        {"error_class": "RuntimeError", "error_message": "boom"},
    )


@pytest.mark.asyncio
async def test_dispatcher_health_tracker_exception_does_not_break_summary():
    tracker = MagicMock()
    tracker.record_attempt.side_effect = RuntimeError("tracker is down")
    dispatcher = CollectorDispatcher(health_tracker=tracker)

    fail_collector = MagicMock()
    fail_collector.collect_from_multiple_sources_async = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    dispatcher.collectors["rss"] = fail_collector

    result = await dispatcher.collect_from_multiple_sources_async(
        {"s1": {"collector_type": "rss"}}
    )
    summary = result["collection_summary"]

    assert summary["sources_failed"] == 1
    assert result["source_details"]["s1"]["success"] is False
    _assert_total_invariant(summary)
