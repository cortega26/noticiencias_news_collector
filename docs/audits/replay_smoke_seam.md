# Replay Smoke Seam (Stable Boundary)

The deterministic Docker smoke path now uses a single public seam on `RSSCollector`:

- API: `RSSCollector.set_feed_replay_source(replay_source: Any | None) -> None`
- Location: `news_collector/collectors/rss_collector.py`

`ReplayFeedSource` (from `news_collector/perf/load_replay.py`) plugs into this seam and provides fixture-backed feed payloads through:

- `ReplayFeedSource.fetch_feed(...) -> dict`

In smoke mode, this avoids external network calls and avoids monkey-patching private collector internals.

## Stability Contract

`set_feed_replay_source` is the intended stable integration point for replay.
Refactors should preserve this method signature and behavior.
