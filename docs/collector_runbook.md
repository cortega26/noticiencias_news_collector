# 🛠️ Collector Runbook

## Overview
The RSS collector fetches scientific feeds on a fixed cadence, applies polite rate limiting, and stores feed metadata for incremental polling. Operators can use this runbook to triage incidents and validate that caching is behaving as expected.

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
