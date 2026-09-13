# Healthcheck runbook

Status: Active. Run from the backend root with its bootstrapped environment.

`scripts/healthcheck.py` checks database connectivity, pending article count
and latest `articles.collected_date`. The collector CLI delegates to the same
healthcheck through `--healthcheck`; it does not run a collection cycle.

```bash
.venv/bin/python scripts/run_collector.py --healthcheck
.venv/bin/python -m scripts.healthcheck --max-pending 50 --max-ingest-minutes 45
```

| Setting | Default | CLI alternatives |
| --- | --- | --- |
| `HEALTHCHECK_MAX_PENDING` | 250 | Collector `--healthcheck-max-pending`; standalone `--max-pending` |
| `HEALTHCHECK_MAX_INGEST_MINUTES` | 180 | Collector `--healthcheck-max-ingest-minutes`; standalone `--max-ingest-minutes` |

Checks report `ok`, `warn` or `fail`. Warnings (such as an empty initial
database) remain healthy; failures produce exit code 1. Backlog above its
threshold fails rather than merely warning. Successful/warning results exit 0.
The command prints human-readable check lines and summary, not a promised
`--json` output format. `tests/test_healthcheck.py` owns regression coverage.

For connectivity failures, inspect the effective SQLite path, permissions,
locks and migration revision. For backlog, inspect real collection errors
and persistence; dry-run cannot establish that pending articles were processed.
For stale ingest, inspect the scheduler and source outcomes before retrying a
normal cycle. Do not flush rows or increase thresholds as a generic repair.

Capture the original output, exit code, configured thresholds and run context.
After remediation, repeat the same check and confirm intended persistence.
A healthy collector database does not prove a frontend deployment is live.
See [../runbook.md](../runbook.md) for workflow leases and callback incidents.
