# Collector runbook

Status: Active. For broader incidents, see [runbook.md](runbook.md).

## Configuration and entrypoints

Use `scripts/run_collector.py` from the backend root with `.venv/bin/python`.
Inspect `--help` before combining operational flags. Runtime settings resolve
through `noticiencias/config_manager.py` and
`news_collector/config/settings.py`; source configuration lives under `config/`,
including the editable `config/sources.yaml` catalog.

For throttling, inspect `[rate_limiting]` in the effective configuration and
source-specific settings. Preserve provider backoff and robots restrictions.
Do not tune concurrency from an old runbook's example environment variables:
confirm supported keys in `docs/config_fields.md` and the active collector.

## Conditional feed requests

Sources persist `feed_etag` and `feed_last_modified` in storage. Collectors
use those validators for conditional requests. A `304` with no new articles
can be a successful poll; compare ingest recency and source outcomes before
classifying it as failure. A server may rotate or omit validators.

Inspect the configured database rather than assuming a fixed file. Avoid
clearing validator state through ad hoc SQL as the first response to a
source outage: establish whether the defect is feed freshness, headers,
rate limiting, parsing or persistence first.

## Reproduction and verification

1. Record source ID, run/trace ID, response code and the relevant error.
2. Reproduce header/backoff behavior with
   `.venv/bin/python -m pytest tests/test_rate_limit_and_backoff.py --no-cov`.
   This is a focused regression check, not the full change-class gate.
3. A targeted command such as
   `.venv/bin/python scripts/run_collector.py --dry-run --sources nature`
   can exercise connectivity. Dry-run still initializes dependencies and
   may cause network/log/cache activity; `--export-json` can write a file. It
   neither drains backlog nor proves persisted throughput.
4. For an intended normal run, compare saved/duplicate/error counts and
   freshness with the preceding baseline. Use the actual logger's fields;
   collector, workflow and CLI events need not share an identical payload.
5. Check the database revision if persistence fails and the active run's
   lease if dispatch stays busy. Follow the operations runbook for recovery.

For performance changes, use [performance_baselines.md](performance_baselines.md)
and record dataset, concurrency, hardware, warm/cold caches and external
provider participation. An offline fixture result does not establish a live
throughput improvement.
