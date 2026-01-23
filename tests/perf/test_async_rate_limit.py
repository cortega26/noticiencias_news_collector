import time
from unittest.mock import AsyncMock, patch

import pytest

from news_collector.collectors.async_rss_collector import AsyncRSSCollector


@pytest.mark.asyncio
async def test_async_rate_limit_enforcement():
    """
    Verify that the AsyncRSSCollector respects domain rate limits when processing a batch.
    """
    collector = AsyncRSSCollector()

    # Config with 3 sources on same domain
    sources_config = {
        "s1": {
            "url": "https://slow-source.com/feed1",
            "name": "S1",
            "category": "tech",
        },
        "s2": {
            "url": "https://slow-source.com/feed2",
            "name": "S2",
            "category": "tech",
        },
        "s3": {
            "url": "https://slow-source.com/feed3",
            "name": "S3",
            "category": "tech",
        },
    }

    # Mock mocks
    # We need to mock _fetch_feed_async (used by _process_single_source_async_with_client -> _collect_from_source_async_internal)
    # The batch method calls _process_single_source_async_with_client

    with patch.object(
        collector, "_collect_from_source_async_internal", new_callable=AsyncMock
    ) as mock_internal:
        # Internal collection matches signature (source_id, config, client)
        mock_internal.return_value = {"success": True, "source_id": "mock"}

        # Mock calculate_effective_delay to return 0.2s
        # Since it is imported locally inside the method, we patch the source module
        with patch(
            "news_collector.collectors.rate_limit_utils.calculate_effective_delay",
            return_value=0.2,
        ):

            start_time = time.perf_counter()

            await collector.collect_from_multiple_sources_async(sources_config)

            duration = time.perf_counter() - start_time

            # 3 sources, same domain.
            # Logic:
            #   loop through group:
            #     process
            #     if not last: sleep(0.2)
            # So sleeps: 2 times = 0.4s

            # Since mock_internal is instant, duration should be dominant by sleep.
            assert duration >= 0.4, f"Rate limit skipped? Duration: {duration:.4f}s"
