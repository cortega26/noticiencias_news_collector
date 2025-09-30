# 🛠️ Collector Runbook

## Overview
The RSS collector fetches scientific feeds on a fixed cadence, applies polite rate limiting, and stores feed metadata for incremental polling. Operators can use this runbook to triage incidents and validate that caching is behaving as expected. For alerting workflows (ingest lag, dedupe drift, etc.) refer to the [Operations Runbook](runbook.md).

## Conditional Fetch Caching
- We persist the latest `ETag` and `Last-Modified` headers per source in the `sources` table (`feed_etag`, `feed_last_modified`).
- Each request includes `If-None-Match` and `If-Modified-Since` when cached values exist. A `304 Not Modified` is treated as a successful poll with zero articles.
- After a `200 OK`, updated headers are written back to the database so the next poll stays incremental. We also accept header refreshes on `304` responses.
- You can inspect the cached values with:
  ```bash
  sqlite3 data/news.db "SELECT id, feed_etag, feed_last_modified FROM sources WHERE id='nature';"
  ```
- If a source stops issuing `ETag`/`Last-Modified`, clear the cache for that entry to force a full refresh:
  ```bash
  sqlite3 data/news.db "UPDATE sources SET feed_etag=NULL, feed_last_modified=NULL WHERE id='nature';"
  ```

## Rate Limiting Overrides
- `config/settings.py` exposes `RATE_LIMITING_CONFIG["domain_overrides"]` for hosts that require extra back-off (e.g. `export.arxiv.org: 20s`, `www.reddit.com: 30s`).
- Individual feeds can enforce stricter pacing via `min_delay_seconds` in `config/sources.py`. This value is merged with robots.txt `crawl-delay` and the domain defaults; the collector uses the most restrictive option.
- When adding a new source, verify Grafana's "collector wait time" panel stays within expectations after a dry run. If the host throttles aggressively, bump the override instead of reducing concurrency.

## Async Collection Mode
- Set `ASYNC_ENABLED=true` to switch `create_system()` to the `AsyncRSSCollector`. The async collector shares the same conditional caching, dedupe, and DLQ logic as the synchronous implementation.
- Concurrency is bounded by `MAX_CONCURRENT_REQUESTS` (async semaphore). Tune it in tandem with outbound bandwidth and DNS limits; start with 8 and increase cautiously while monitoring socket exhaustion.
- Per-domain throttling is still enforced: async tasks acquire a domain-specific lock before hitting the network, so overrides and `min_delay_seconds` stay honored even with dozens of concurrent feeds.
- Before enabling in production, run `pytest tests/perf/test_async_collector_perf.py` to confirm throughput improvements and `pytest tests/test_async_collector_parity.py` to ensure robots/headers parity remains intact.
- After rollout, watch Grafana's response-code mix and queue depth. If 429s spike, lower `MAX_CONCURRENT_REQUESTS` or tighten the domain overrides rather than disabling async entirely.

## Incident Checklist
1. **Spike in HTTP 304s**
   - Confirm schedules: repeated 304s with zero articles are expected when no new stories land.
   - Validate last article timestamps in the DB to ensure fresh posts are still detected.
2. **Unexpected 200 payload despite cache**
   - Inspect stored metadata to confirm the server rotated the ETag.
   - Capture headers with `curl -I <feed>` and compare with stored values.
3. **Server ignores validators**
   - Disable caching temporarily by clearing metadata (see above) and set a reminder to re-enable once the provider fixes headers.
4. **Database migration issues**
   - Ensure the new columns exist: `PRAGMA table_info(sources);` should list `feed_etag` and `feed_last_modified`.

## Verification Steps After Deploying Collector Changes
1. Run `pytest tests/test_rate_limit_and_backoff.py -k conditional` to ensure regression coverage for cached headers.
2. Trigger a dry run (`python run_collector.py --dry-run --sources nature`) and confirm logs show the conditional request headers.
3. Review Grafana panels for fetch duration and response codes to verify fewer bytes transferred after deploying caching.

## Structured Logging Reference
- Every collector cycle emits structured log dictionaries. Core fields:
  - `trace_id`: stable per cycle; follows the CLI trace id when triggered via `run_collector.py`.
  - `session_id`: human-readable session handle (e.g. `abc123-20250203-153045`).
  - `source_id`: collector source or logical module (`system`, `cli`).
  - `latency`: seconds spent in the operation.
- Sample entries:
  ```json
  {
    "event": "collection_cycle.start",
    "trace_id": "a0c7e4f1-2cbe-4d97-9baf-ef5a1b4d8e2c",
    "session_id": "0fb12c-20250203-153045",
    "source_id": "system",
    "latency": 0.0,
    "details": {"dry_run": false, "source_filter": "all"}
  }
  {
    "event": "collector.source.failed",
    "trace_id": "a0c7e4f1-2cbe-4d97-9baf-ef5a1b4d8e2c",
    "session_id": "0fb12c-20250203-153045",
    "source_id": "esa",
    "latency": 2.41,
    "details": {"articles_found": 0, "articles_saved": 0, "error_message": "timeout"}
  }
  {
    "event": "cli.collection.completed",
    "trace_id": "a0c7e4f1-2cbe-4d97-9baf-ef5a1b4d8e2c",
    "session_id": "0fb12c-20250203-153045",
    "source_id": "cli",
    "latency": 186.2,
    "details": {"sources_processed": 42, "articles_saved": 118}
  }
  ```

## Troubleshooting Flow

### Collector Failure
1. Locate the corresponding `collector.source.failed` log entry using the `trace_id` from the CLI or scheduler trigger.
2. Inspect `details.error_message`; retry transient network errors, but investigate rate limits or credential drift for persistent failures.
3. Check metrics: `collector.ingest.error` tagged with the same `trace_id` and `source_id` confirms the error was emitted to telemetry.
4. If repeated failures occur, pause the source in `config/sources.py` and notify content owners; document mitigation in the ops log.

### Scoring Error
1. Search for `collection_cycle.error` events; they include the serialized exception under `details.error` with the active `trace_id`.
2. Use `session_id` to pull staging articles for the problematic run from the database (`SELECT * FROM scored_articles WHERE session_id=?`).
3. Run `pytest tests/test_scoring_pipeline.py -k <feature>` to reproduce locally. The metrics reporter will emit `collector.ingest.count` entries up to the failure point—confirm no duplicate scoring attempts afterward.
4. Apply fixes, re-run the collector in dry-run mode, and verify `collection_cycle.completed` appears with a non-zero latency and expected article counts before redeploying.
