"""Plan 125: bounded enrichment fan-out — equivalence, isolation, pacing.

Fan-out lives in RSSCollector._extract_articles_from_feed: route_enrichment
is dispatched into a bounded ThreadPoolExecutor (phase 1) while fallback /
metadata / image logic stays serial in input order (phase 2). These tests
prove the three load-bearing properties:

- equivalence: fanned output identical to the pre-125 serial loop
  (order + fallback shapes + metadata);
- isolation: one raise drops only that candidate, rest unaffected;
- pacing: per-host concurrency never exceeds HostPacer's cap under fan-out.
"""

import copy
import threading
import time
from unittest.mock import MagicMock, patch

from news_collector.collectors import rss_collector as rss_module
from news_collector.collectors.rss_collector import RSSCollector
from news_collector.enrichment.host_pacer import HostPacer
from news_collector.enrichment.router import EnrichmentStrategyRouter


def _collector():
    with patch("news_collector.collectors.base_collector.get_database_manager"):
        from unittest.mock import MagicMock as MM

        from noticiencias.config_manager import load_config

        return RSSCollector(logger_factory=MM(), config=load_config())


def _drive_extraction(collector, candidates, route_fn, source_config=None):
    """Run _extract_articles_from_feed with network seams stubbed."""
    from news_collector.config.settings import refresh_runtime_config

    source_config = source_config or {"url": "http://feed.com"}
    parser_mock = MagicMock()
    # Deep-copy so the collector's in-place cand mutation never leaks
    # between the serial reference and the fanned run.
    parser_mock.extract_items.return_value = copy.deepcopy(candidates)
    collector.parser = parser_mock
    db = MagicMock()
    db.articles_exist.return_value = set()
    collector.db_manager = db
    collector.pre_scorer = MagicMock()
    collector.pre_scorer.model_name = "ollama"
    collector.router = MagicMock(route_enrichment=route_fn)
    collector.image_extractor = MagicMock()
    collector.image_extractor.validate_image.return_value = False
    collector.image_extractor.extract_candidates.return_value = []
    collector._emit_log = MagicMock()
    refresh_runtime_config()
    return collector._extract_articles_from_feed(MagicMock(), source_config, "s1")


def _serial_reference(candidates, route_fn, source_config):
    """Pre-125 serial loop, copied verbatim for equivalence comparison.

    Any divergence between this and the fanned path is a STOP condition.
    """
    articles = []
    for cand in copy.deepcopy(candidates):
        try:
            cand.setdefault(
                "content_mode", source_config.get("content_mode", "full_text")
            )
            enrichment_result = route_fn("s1", source_config, cand)
            cand["content"] = enrichment_result.get("content", "")
            html_content = enrichment_result.get("raw_content") or ""
            if enrichment_result.get("metadata"):
                cand["enrichment_metadata"] = enrichment_result["metadata"]
            if not cand.get("content"):
                cand["content"] = cand.get("summary", "")
                effective = cand.get("content_mode") or source_config.get(
                    "content_mode", "full_text"
                )
                if cand["content"] and effective != "summary_only":
                    cand["content_mode"] = "summary_fallback"
            if "article_metadata" not in cand:
                cand["article_metadata"] = {}
            cand["_image_status"] = (
                "IMAGE_DOWNLOAD_FAILED" if not html_content else "IMAGE_MISSING_SOURCE"
            )
            cand["_image_source"] = None
            if "entry_ref" in cand:
                del cand["entry_ref"]
            articles.append(cand)
        except Exception:
            continue
    return articles


def _candidates(n=5):
    return [
        {
            "title": f"Article title {i} long enough",
            "url": f"https://fanout.example.com/a{i}",
            "summary": f"summary-{i} " * 10,
            "published_date": None,
        }
        for i in range(n)
    ]


def test_equivalence_order_and_fallback_shapes_match_serial():
    """Fanned output must be identical to the serial loop (order + shapes)."""
    cands = _candidates()

    def route_fn(source_id, source_config, cand):
        i = int(cand["url"].rsplit("a", 1)[-1])
        time.sleep(0.01 * (5 - i))  # staggered latency: proves order, not finish order
        if i == 1:
            return {
                "success": False,
                "reason": "http_403",
                "strategy_used": "http",
                "content": "",
                "raw_content": None,
            }
        if i == 2:
            return {
                "success": True,
                "content": "X" * 600,
                "raw_content": "<html>x</html>",
                "strategy_used": "http",
                "metadata": {"doi": "10.1/x"},
            }
        if i == 3:
            return {
                "success": False,
                "reason": "discovery_only",
                "strategy_used": "none",
                "content": "",
            }
        return {
            "success": True,
            "content": "Y" * 700,
            "raw_content": "<html>y</html>",
            "strategy_used": "http",
        }

    source_config = {"url": "http://feed.com", "content_mode": "full_text"}
    fanned = _drive_extraction(_collector(), cands, route_fn, dict(source_config))
    serial = _serial_reference(cands, route_fn, source_config)

    assert [a["url"] for a in fanned] == [a["url"] for a in serial]
    assert fanned == serial
    # Spot-check fallback shapes: failure → summary fallback, success keeps content.
    by_url = {a["url"]: a for a in fanned}
    assert by_url["https://fanout.example.com/a1"]["content_mode"] == "summary_fallback"
    assert by_url["https://fanout.example.com/a2"]["enrichment_metadata"] == {
        "doi": "10.1/x"
    }
    assert by_url["https://fanout.example.com/a0"]["content"] == "Y" * 700


def test_isolation_one_raise_drops_only_that_candidate():
    """A raise in one article must not cancel the rest (gather isolation)."""
    cands = _candidates()[:4]

    def route_fn(source_id, source_config, cand):
        if cand["url"].endswith("/a2"):
            raise RuntimeError("boom")
        return {
            "success": True,
            "content": "Z" * 600,
            "raw_content": "<html/>",
            "strategy_used": "http",
        }

    col = _collector()
    arts = _drive_extraction(col, cands, route_fn)
    urls = [a["url"] for a in arts]
    assert "https://fanout.example.com/a2" not in urls
    assert urls == [
        "https://fanout.example.com/a0",
        "https://fanout.example.com/a1",
        "https://fanout.example.com/a3",
    ]
    # The failure travels the same process_failed path as serial.
    events = [c.args[1] for c in col._emit_log.call_args_list]
    assert "collector.article.process_failed" in events


def test_pacing_per_host_cap_never_exceeded_under_fanout():
    """With HostPacer max_concurrency=1, same-host fetches never overlap."""
    peak = {"cur": 0, "max": 0}
    lock = threading.Lock()

    clock_holder = {}

    def fake_enrich(url, *a, **k):
        with lock:
            peak["cur"] += 1
            peak["max"] = max(peak["max"], peak["cur"])
        try:
            time.sleep(0.05)
            return {
                "success": True,
                "content": "P" * 600,
                "raw_content": "<html/>",
                "status_code": 200,
            }
        finally:
            with lock:
                peak["cur"] -= 1

    col = _collector()
    router = EnrichmentStrategyRouter(
        host_pacer=HostPacer(
            min_interval_seconds=0, max_concurrency=1, max_wait_seconds=10.0
        )
    )
    router.logger = MagicMock()
    router.http = MagicMock()
    router.http.enrich.side_effect = fake_enrich
    router.scholarly = MagicMock()
    router.headless = MagicMock()
    router.scrapling = MagicMock()
    router.scrapling_http = MagicMock()
    clock_holder["router"] = router

    cands = [
        {
            "title": f"Paced article {i} long enough",
            "url": f"https://paced.example.com/p{i}",
            "summary": "s " * 20,
            "published_date": None,
        }
        for i in range(4)
    ]
    from news_collector.config.settings import refresh_runtime_config

    parser_mock = MagicMock()
    parser_mock.extract_items.return_value = copy.deepcopy(cands)
    col.parser = parser_mock
    db = MagicMock()
    db.articles_exist.return_value = set()
    col.db_manager = db
    col.pre_scorer = MagicMock()
    col.pre_scorer.model_name = "ollama"
    col.router = router
    col.image_extractor = MagicMock()
    col.image_extractor.validate_image.return_value = False
    col.image_extractor.extract_candidates.return_value = []
    col._emit_log = MagicMock()
    refresh_runtime_config()
    with (
        patch("news_collector.enrichment.router.validate_url_safety", MagicMock()),
        patch("news_collector.enrichment.router.enrichment_metrics", MagicMock()),
        patch("news_collector.enrichment.router.strategy_lock_manager", MagicMock()),
        patch("news_collector.enrichment.router.strategy_optimizer", MagicMock()),
    ):
        arts = col._extract_articles_from_feed(
            MagicMock(),
            {"url": "http://feed.com", "enrichment_strategy": "http"},
            "s1",
        )

    assert len(arts) == 4
    assert peak["max"] == 1
    assert [a["url"] for a in arts] == [c["url"] for c in cands]


def test_fanout_bound_is_coupled_to_pacer_cap():
    """The pool cap stays within the documented 4–8 window."""
    assert 4 <= rss_module._ENRICHMENT_FANOUT_WORKERS <= 8


def test_metrics_recorders_thread_safe_under_fanout():
    """Concurrent record_* calls must not lose events (metrics parity).

    The store already serializes every buffer mutation and flush under an
    RLock with check_same_thread=False; this test proves the hit path
    (attempt + success per article) keeps exact counts under fan-out.
    """
    import tempfile

    from news_collector.observability.enrichment_metrics_store import (
        EnrichmentMetricsStore,
    )

    with tempfile.TemporaryDirectory() as td:
        store = EnrichmentMetricsStore.create_isolated(
            environment="test", db_path=f"{td}/m.db", flush_batch_size=1
        )
        source_id = "fanout-metrics-src"

        def worker(i):
            store.record_attempt(source_id, "http")
            store.record_success(source_id, "http", 0.1, 600, True)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        row = store.get_metrics(source_id)
        assert row is not None
        assert row["total_discovered"] == 8
        assert row["total_enrichment_attempted"] == 8
        assert row["http_attempts"] == 8
        assert row["http_success"] == 8
        assert row["total_publishable"] == 8
        store.close()
