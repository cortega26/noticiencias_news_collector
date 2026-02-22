import os
import random
import time
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from news_collector.collectors.html_collector import HtmlCollector

# Benchmark Parameters
DEFAULT_CYCLES = 80
SUCCESS_THRESHOLD = 0.95
DEFAULT_MAX_RUNTIME_SECONDS = 3.0


def _build_response(status_code, text="", content=None, headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.text = text
    response.content = content if content is not None else text.encode("utf-8")
    return response


@pytest.mark.asyncio
@pytest.mark.perf
async def test_reliability_benchmark_200_cycles():
    """
    Quantitative Benchmark:
    - Runs N deterministic cycles of fetching (default 80, opt-in 200+ via env var).
    - Mix of response types: 200 (Success), 304 (Success), 403, 404, 429, 500, Timeout.
    - Measures Success Rate.
    """
    cycles = int(os.getenv("NOTICIENCIAS_BENCH_CYCLES", str(DEFAULT_CYCLES)))
    max_runtime_seconds = float(
        os.getenv("NOTICIENCIAS_BENCH_MAX_SECONDS", str(DEFAULT_MAX_RUNTIME_SECONDS))
    )
    rng = random.Random(42)

    results = {
        "total": 0,
        "success": 0,
        "retry_loops": 0,
        "cooldowns_triggered": 0,
        "errors": Counter(),
    }

    collector = HtmlCollector()
    collector.db_manager = MagicMock()
    collector.db_manager.get_source_circuit_state.return_value = {"status": "ACTIVE"}
    collector.db_manager.get_source_feed_metadata.return_value = {}
    collector.db_manager.update_source_feed_metadata = MagicMock()
    collector.db_manager.update_source_circuit_state = MagicMock()

    call_plan = {}
    scenario_by_cycle = {}
    terminal_status_by_cycle = {}
    planned_get_calls_by_cycle = Counter()
    for cycle_id in range(cycles):
        case = rng.random()
        if case < 0.70:
            scenario = "ok_200"
            plan = [_build_response(200, text="<html>Success</html>")]
            terminal_status = 200
        elif case < 0.80:
            scenario = "not_modified_304"
            plan = [_build_response(304)]
            terminal_status = 304
        elif case < 0.90:
            scenario = "transient_5xx_recovered"
            plan = [
                _build_response(500),
                _build_response(200, text="Recovered", content=b"Recovered"),
            ]
            terminal_status = 200
        elif case < 0.95:
            scenario = "rate_limited_429"
            plan = [_build_response(429, headers={"Retry-After": "60"})]
            terminal_status = 429
        elif case < 0.98:
            scenario = "forbidden_403"
            plan = [_build_response(403)]
            terminal_status = 403
        else:
            scenario = "not_found_404"
            plan = [_build_response(404)]
            terminal_status = 404

        call_plan[cycle_id] = plan
        scenario_by_cycle[cycle_id] = scenario
        terminal_status_by_cycle[cycle_id] = terminal_status
        planned_get_calls_by_cycle[cycle_id] = len(plan)

    expected_5xx_cycles = sum(
        1
        for scenario in scenario_by_cycle.values()
        if scenario == "transient_5xx_recovered"
    )
    expected_429_cycles = sum(
        1 for scenario in scenario_by_cycle.values() if scenario == "rate_limited_429"
    )
    assert (
        expected_5xx_cycles > 0
    ), "Benchmark mix produced no 5xx retries; increase NOTICIENCIAS_BENCH_CYCLES."
    assert (
        expected_429_cycles > 0
    ), "Benchmark mix produced no 429 cooldowns; increase NOTICIENCIAS_BENCH_CYCLES."

    get_calls_by_cycle = Counter()

    async def mock_get(url, *args, **kwargs):
        del args, kwargs
        cycle_id = int(str(url).rsplit("/", 1)[-1])
        get_calls_by_cycle[cycle_id] += 1
        responses = call_plan.get(cycle_id)
        assert responses is not None, f"Unexpected URL requested by collector: {url}"
        assert responses, f"No responses remaining for cycle_id={cycle_id}, url={url}"
        return responses.pop(0)

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("random.uniform", return_value=0.1),
        patch.object(collector, "_respect_robots", return_value=(True, 0)),
        patch.object(collector, "_enforce_domain_rate_limit", return_value=None),
    ):
        mock_instance = mock_client_cls.return_value
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.get = AsyncMock(side_effect=mock_get)

        start = time.monotonic()
        for cycle_id in range(cycles):
            source_config = {
                "url": f"http://bench.com/{cycle_id}",
                "crawl_interval_seconds": 60,
            }
            stats = await collector.collect_from_source_async(
                f"src_{cycle_id}", source_config
            )
            scenario = scenario_by_cycle[cycle_id]
            expected_success = scenario in {
                "ok_200",
                "not_modified_304",
                "transient_5xx_recovered",
            }
            assert (
                stats["success"] is expected_success
            ), f"Unexpected success state for cycle {cycle_id} ({scenario}): {stats}"

            status_code = terminal_status_by_cycle[cycle_id]
            results["total"] += 1
            if stats["success"]:
                results["success"] += 1
            else:
                if status_code == 429:
                    results["cooldowns_triggered"] += 1
                results["errors"][status_code] += 1

        elapsed = time.monotonic() - start

    results["retry_loops"] = sum(
        1
        for cycle_id, scenario in scenario_by_cycle.items()
        if scenario == "transient_5xx_recovered" and get_calls_by_cycle[cycle_id] > 1
    )

    success_rate = results["success"] / results["total"]
    stable_count = (
        results["success"]
        + results["cooldowns_triggered"]
        + results["errors"][403]
        + results["errors"][404]
    )
    stability_rate = stable_count / results["total"]

    assert (
        elapsed <= max_runtime_seconds
    ), f"Benchmark runtime {elapsed:.3f}s exceeded {max_runtime_seconds:.3f}s for {cycles} cycles."
    assert (
        results["retry_loops"] == expected_5xx_cycles
    ), "5xx retries were not executed for all transient failures."
    assert (
        mock_sleep.await_count == expected_5xx_cycles
    ), "Backoff sleep should be awaited exactly once per transient 5xx cycle."
    assert (
        collector.db_manager.update_source_circuit_state.call_count
        == expected_429_cycles
    ), "Cooldown updates must match the number of 429 cycles."
    for call in collector.db_manager.update_source_circuit_state.call_args_list:
        assert call.kwargs.get("force_cooldown_until") is not None
    for cycle_id, scenario in scenario_by_cycle.items():
        expected_calls = planned_get_calls_by_cycle[cycle_id]
        assert (
            get_calls_by_cycle[cycle_id] == expected_calls
        ), f"Unexpected number of HTTP calls for cycle {cycle_id} ({scenario})."
    assert sum(get_calls_by_cycle.values()) == sum(planned_get_calls_by_cycle.values())
    assert success_rate >= 0.80, f"Success rate unexpectedly low: {success_rate:.2%}"

    assert (
        stability_rate >= SUCCESS_THRESHOLD
    ), f"Stability rate {stability_rate:.2%} below threshold {SUCCESS_THRESHOLD:.0%}"
