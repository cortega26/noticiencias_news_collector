# Healthcheck Runbook

## Overview
The collector healthcheck validates three operational pillars before each scheduled run:

1. **Database connectivity** – verifies the backing SQL engine responds to trivial queries.
2. **Queue backlog** – counts pending articles (`processing_status == 'pending'`) and compares the total against a configurable threshold.
3. **Latest ingest recency** – checks the timestamp of the most recent `articles.collected_date` entry to ensure fresh data is flowing.

The CLI entry point is shared between `run_collector.py --healthcheck` and the standalone module `python -m scripts.healthcheck`. All checks emit structured output and exit with status code `0` on success (including warnings) or `1` on failure.

## Configuration knobs
| Name | Type | Default | Required | Description |
| --- | --- | --- | --- | --- |
| `--healthcheck-max-pending` / `--max-pending` | integer | `HEALTHCHECK_MAX_PENDING` env or `250` | No | Maximum backlog allowed before the queue check fails. |
| `--healthcheck-max-ingest-minutes` / `--max-ingest-minutes` | integer | `HEALTHCHECK_MAX_INGEST_MINUTES` env or `180` | No | Maximum allowed lag (minutes) between now and the latest ingest timestamp. |
| `HEALTHCHECK_MAX_PENDING` | integer | `250` | No | Environment override applied to both CLI entry points for backlog threshold. |
| `HEALTHCHECK_MAX_INGEST_MINUTES` | integer | `180` | No | Environment override applied to both CLI entry points for ingest freshness threshold. |

Invoke the CLI with explicit thresholds to match maintenance windows or CI expectations:

```bash
python run_collector.py --healthcheck --healthcheck-max-pending 50 --healthcheck-max-ingest-minutes 45
# or via the standalone module
env HEALTHCHECK_MAX_PENDING=100 python -m scripts.healthcheck --max-ingest-minutes 60
```

## Interpreting results
Each check emits one line prefixed with an emoji:

- `✅ database` – DB connection succeeded.
- `⚠️ queue_backlog` – backlog over threshold but not critical. Investigate before next run.
- `❌ latest_ingest` – ingest lag exceeded the configured threshold.

Status semantics:

| Status | Exit impact | Meaning |
| --- | --- | --- |
| `ok` | Healthy | Check passed with room to spare. |
| `warn` | Healthy | The system is in a degraded-but-acceptable state (e.g., empty databases on first boot). Document and monitor. |
| `fail` | Unhealthy | Immediate remediation required; CLI exits with status `1`. |

Warnings never block the pipeline but should trigger manual review. Failures stop the automation and bubble the exit code to CI.

## Common failures & remediation
| Symptom | Likely cause | Remedy |
| --- | --- | --- |
| `database` = `❌` with `Database query failed` | Engine down, credentials rotated, or schema migration mid-flight. | Check service health, rotate credentials, rerun `make config-validate`. Retry healthcheck after DB recovers. |
| `queue_backlog` = `❌` | Pending articles exceed threshold. | Run `python run_collector.py --dry-run` to confirm throughput. Consider scaling workers or flushing stale jobs. |
| `latest_ingest` = `❌` with large lag | Collector not running or downstream storage failing. | Inspect collector logs (`collector.fetch.*` events) for errors, run a manual collection, and ensure scoring/storage jobs succeed. |
| `latest_ingest` = `⚠️` with message "No ingestion records found" | Fresh environment with empty database. | Run an initial collection cycle; warning clears once articles are ingested. |

## Structured logging reference
During healthcheck-triggered runs, collectors now emit the following event families:

- `collector.batch.start` / `collector.batch.completed` – batch lifecycle with `trace_id`, `session_id`, aggregate counters, and latency.
- `collector.source.completed` / `collector.source.failed` – per-source outcomes including `articles_found`, `articles_saved`, and error messages.
- `collector.article.saved` – persistence success with `article_id`, `source_id`, and truncated title.
- `collector.article.process_error` / `collector.article.validation_failed` – payload issues routed to DLQ with associated URLs.

These events allow operators to correlate CLI output with fine-grained collector behaviour using the same `trace_id` emitted by the healthcheck wrapper.

## Escalation checklist
1. Run `python run_collector.py --healthcheck --healthcheck-max-pending <current backlog + 10>` to confirm reproducibility.
2. Capture the JSON summary (`--json` flag coming soon; meanwhile redirect stdout) and attach to the incident ticket.
3. Cross-reference `collector.article.saved` counts against DB metrics to ensure no silent drops.
4. If failures persist after remediation, page the on-call data engineer and reference this runbook in the ticket.
