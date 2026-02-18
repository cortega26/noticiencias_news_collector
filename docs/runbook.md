# Operations Runbook

This runbook documents the two paging alerts that matter most for the Noticiencias pipeline today. Each section explains what
triggers the alert, how to triage it, and which tools to use when you are in the middle of an incident.

## Alert Catalogue

### 1. Ingest Lag Breach
- **Signal**: Grafana alert `pipeline.ingest.lag_p95_minutes` (warning at 12 min, page at 18 min) or `python run_collector.py --healthcheck` returning a non-zero exit code.
- **Impact**: Homepage stops showing newly published research; downstream enrichment and reranker backlogs accumulate.
- **Primary owner**: Collector on-call.

#### Diagnosis Workflow
1. **Run the CLI healthcheck** to validate connectivity and queue depth without waiting on dashboards:
   ```bash
   python run_collector.py --healthcheck
   ```
   - Articles waiting above the default threshold (250) or an ingest lag older than 180 minutes will fail the check.
   - Override thresholds when debugging chronic backlogs by exporting `HEALTHCHECK_MAX_PENDING=500` before invoking the CLI.
2. **Inspect scheduler freshness**. Tail the structured logs for `collection_cycle.start`/`collection_cycle.completed` events and confirm cycles are still firing.
   ```bash
   sqlite3 data/news.db "SELECT MAX(collected_date) FROM articles;"
   ```
3. **Look for source specific failures** in the `sources` table. High `consecutive_failures` or stale `last_article_found` timestamps often indicate credential or robots.txt issues.
   ```bash
   sqlite3 data/news.db "SELECT id, last_article_found, consecutive_failures FROM sources ORDER BY consecutive_failures DESC LIMIT 10;"
   ```
4. **Check the DLQ** (`data/dlq/`). Files named `rss_<source>_*.json` represent payloads that failed to persist—open one to inspect the error context.

#### Remediation Steps
- **Transient network spikes**: re-run the collector in dry-run mode to confirm reachability.
  ```bash
  python run_collector.py --dry-run --sources nature mit_news
  ```
- **Rate limit throttling**: adjust `RATE_LIMITING_CONFIG["domain_overrides"]` or the per-source `min_delay_seconds` in `config/sources.py` and redeploy.
- **Persistent parser failures**: replay the offending source through `scripts/replay_outage.py` with the fixture from `tests/data/monitoring/` to validate fixes before production.
- **Database outage**: restart the managed SQLite/Postgres service and re-run `python run_collector.py --healthcheck` to verify the backlog clears.

#### Verification
- Healthcheck exits with code `0` and reports a fresh ingest timestamp.
- Grafana lag panel drops below 12 minutes within two pipeline cycles.
- No new files land in `data/dlq/` for the affected sources.

### 2. Dedupe Drift
- **Signal**: Alert `dedupe.near_duplicate_f1` (warning <0.93, page <0.90) or noticeable duplicate clusters in the ranked feed.
- **Impact**: Users see repeated stories; reranker diversity guarantees no longer hold; scoring explanations degrade.
- **Primary owner**: Dedupe/quality SME.

#### Diagnosis Workflow
1. **Quantify the drift** by running the regression suite:
   ```bash
   pytest tests/test_dedupe_utils.py
   python scripts/dedupe_tuning.py --report
   ```
2. **Check recent clustering metrics** in the database:
   ```bash
   sqlite3 data/news.db "SELECT COUNT(*) FROM articles WHERE duplication_confidence > 0.8 AND collected_date > datetime('now', '-1 day');"
   ```
3. **Review canonicalization health** using the benchmark helper:
   ```bash
   python scripts/benchmark_canonicalize.py --sources nature science
   ```
4. **Inspect suspicious clusters** directly:
   ```bash
   python scripts/recluster_articles.py --cluster-id <uuid>
   ```

#### Remediation Steps
- **Tokenizer or normalization regression**: roll back the offending commit or hotfix `src/utils/text_cleaner.py`, then rerun `pytest tests/test_text_cleaner.py` and `tests/test_dedupe_utils.py`.
- **SimHash threshold tuning**: adjust `DEDUP_CONFIG["simhash_threshold"]` in `config/settings.py` and validate with `scripts/dedupe_tuning.py --simulate` before applying to production.
- **Source specific anomalies**: temporarily suppress the source via `config/sources.py` (`is_active: false`) and coordinate with content owners.

#### Verification
- Run `python run_collector.py --healthcheck` to ensure backlog articles are processing normally after dedupe fixes.
- Confirm Grafana dedupe F1 recovers above 0.95 and manual spot-checks show diverse top stories.
- Clear any temporary source suppressions after data quality stabilises.

## Tooling Reference
- `python run_collector.py --healthcheck` — fast signal for DB connectivity, queue backlog, and ingest recency.
- `scripts/replay_outage.py` — reproduce historical outages and validate mitigations.
- `scripts/dedupe_tuning.py` — stress-test SimHash thresholds.
- `scripts/benchmark_canonicalize.py` — verify URL normalization after rule changes.
- `docs/collector_runbook.md` — collector-specific operational guidance.
